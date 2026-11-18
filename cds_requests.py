"""Send CDS requests one at a time, resume them after a restart, and log timing.

ECMWF asks users to submit Climate Data Store requests sequentially, so
``run_request`` blocks until its job has finished (or been deleted) before it
returns, and callers run requests in a plain loop. Each job's request ID is
saved in a state file next to the output so a restarted run reattaches to a
job still queued at CDS instead of submitting a duplicate.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

import requests
from ecmwf.datastores.processing import ProcessingFailedError

logger = logging.getLogger(__name__)

STATE_FILE_NAME = ".cds_requests.json"
WAITING_STATUSES = ("accepted", "running")


class RequestRejectedError(RuntimeError):
    """CDS rejected the request; sending it again would be rejected again."""


class RequestFailedError(RuntimeError):
    """A CDS job ended without results (failed, dismissed or deleted)."""


class OutputCheckError(RuntimeError):
    """A downloaded file did not pass the caller's check."""


def request_hash(dataset: str, request: dict[str, Any]) -> str:
    """Stable hash of the dataset and request, used to match a saved job."""
    payload = json.dumps([dataset, request], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_then_rename(
    check: Callable[[Path], tuple[bool, str]], target: Path
) -> Callable[[Path], None]:
    """Build a finalize step that moves the download to ``target`` only if
    ``check(path)`` returns ``(True, reason)``."""

    def finalize(temp_path: Path) -> None:
        ok, reason = check(temp_path)
        if not ok:
            raise OutputCheckError(f"{target}: {reason}")
        temp_path.replace(target)

    return finalize


def _default_client():
    # cdsapi reads ~/.cdsapirc inside the library; this project never opens it.
    import cdsapi

    return cdsapi.Client().client


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


def _save_state(state_path: Path, state: dict) -> None:
    temp = state_path.with_name(state_path.name + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True))
    temp.replace(state_path)


def _is_client_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    return (
        isinstance(exc, requests.HTTPError)
        and response is not None
        and 400 <= response.status_code < 500
    )


def _failure_message(remote) -> str:
    try:
        remote.results_ready
    except ProcessingFailedError as exc:
        return str(exc)
    return ""


def _seconds(start, end) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _fmt(seconds: float | None) -> str:
    return "n/a" if seconds is None else f"{seconds:.1f}s"


def run_request(
    dataset: str,
    request: dict[str, Any],
    target: Path,
    finalize: Callable[[Path], None],
    *,
    client=None,
    max_attempts: int = 4,
    backoff_seconds: float = 60.0,
    poll_seconds: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run one CDS request to completion and hand its download to ``finalize``.

    The download is written to a temporary name beside ``target``, then
    ``finalize(temp_path)`` installs it (see ``check_then_rename``) or raises
    ``OutputCheckError`` to have the request retried. Transport errors,
    failed jobs and check failures are retried up to ``max_attempts`` times,
    waiting ``backoff_seconds`` and doubling after each attempt. A rejected
    job raises ``RequestRejectedError`` at once and is never resubmitted.
    """
    target = Path(target)
    client = client if client is not None else _default_client()
    state_path = target.parent / STATE_FILE_NAME
    key = target.name
    wanted_hash = request_hash(dataset, request)
    temp_path = target.with_name(f"{target.stem}.partial{target.suffix}")

    def clear_saved():
        state = _load_state(state_path)
        if state.pop(key, None) is not None:
            _save_state(state_path, state)

    for attempt in range(1, max_attempts + 1):
        try:
            saved = _load_state(state_path).get(key)
            if saved and saved["request_hash"] != wanted_hash:
                # A job for an older version of this request: remove it at
                # CDS so it never sits queued beside the new one.
                logger.info("Deleting stale CDS job %s", saved["request_id"])
                try:
                    client.delete(saved["request_id"])
                except requests.HTTPError as exc:
                    if not _is_client_error(exc):
                        raise
                clear_saved()
                saved = None
            if saved:
                logger.info("Reattaching to CDS job %s", saved["request_id"])
                remote = client.get_remote(saved["request_id"])
            else:
                remote = client.submit(dataset, request)
                state = _load_state(state_path)
                state[key] = {
                    "request_id": remote.request_id,
                    "request_hash": wanted_hash,
                }
                _save_state(state_path, state)

            status = remote.status
            while status in WAITING_STATUSES:
                sleep(poll_seconds)
                status = remote.status
            if status == "rejected":
                clear_saved()
                raise RequestRejectedError(
                    f"CDS rejected {dataset} request for {target}: "
                    f"{_failure_message(remote)}"
                )
            if status != "successful":
                clear_saved()
                raise RequestFailedError(
                    f"CDS job {remote.request_id} for {target} ended {status}: "
                    f"{_failure_message(remote)}"
                )

            transfer_start = time.monotonic()
            try:
                remote.download(str(temp_path))
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
            transfer = time.monotonic() - transfer_start
            try:
                finalize(temp_path)
            except OutputCheckError:
                # Resubmit rather than re-download the same result.
                clear_saved()
                raise
            finally:
                temp_path.unlink(missing_ok=True)
            clear_saved()

            started_at = remote.started_at
            logger.info(
                "CDS request dataset=%s target=%s queue=%s run=%s transfer=%s cache_hit=%s",
                dataset,
                target,
                _fmt(_seconds(remote.created_at, started_at)),
                _fmt(_seconds(started_at, remote.finished_at)),
                _fmt(transfer),
                started_at is None,
            )
            return
        except RequestRejectedError as exc:
            logger.error("%s", exc)
            raise
        except requests.HTTPError as exc:
            if _is_client_error(exc):
                # CDS refused the request or no longer knows the saved job;
                # repeating it would fail the same way.
                clear_saved()
                raise
            error = exc
        except (RequestFailedError, OutputCheckError, requests.RequestException) as exc:
            error = exc
        if attempt == max_attempts:
            raise error
        wait = backoff_seconds * 2 ** (attempt - 1)
        logger.warning(
            "CDS attempt %d/%d for %s failed (%s); retrying in %.0fs",
            attempt,
            max_attempts,
            target,
            error,
            wait,
        )
        sleep(wait)
