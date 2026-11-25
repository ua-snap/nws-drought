"""Tests for the sequential CDS request runner.

Every test uses a fake datastores client, so nothing here contacts CDS.
"""

import datetime
import json
import logging

import pytest
import requests
from ecmwf.datastores.processing import ProcessingFailedError

import cds_requests
from cds_requests import (
    OutputCheckError,
    RequestRejectedError,
    request_hash,
    run_request,
)

DATASET = "reanalysis-era5-land"


def check_then_rename(check, target):
    """A finalize step that installs the download at ``target`` only if
    ``check(path)`` passes."""

    def finalize(temp_path):
        ok, reason = check(temp_path)
        if not ok:
            raise OutputCheckError(f"{target}: {reason}")
        temp_path.replace(target)

    return finalize


REQUEST = {"variable": ["total_precipitation"], "year": "2026", "month": ["08"]}
CREATED = datetime.datetime(2026, 11, 18, 12, 0, 0)


class _FakeRemote:
    """Stand-in for ecmwf.datastores.Remote that plays a scripted status."""

    def __init__(self, client, request_id, final_status, message="", started=True):
        self.client = client
        self.request_id = request_id
        self.final_status = final_status
        self.message = message
        self.created_at = CREATED
        self.started_at = CREATED + datetime.timedelta(seconds=30) if started else None
        self.finished_at = CREATED + datetime.timedelta(seconds=100)

    @property
    def status(self):
        # A job leaves the active set once CDS reports a terminal status.
        self.client.active.discard(self.request_id)
        return self.final_status

    @property
    def results_ready(self):
        if self.final_status in ("failed", "rejected"):
            raise ProcessingFailedError(self.message)
        return self.final_status == "successful"

    def download(self, target=None):
        self.client.downloads.append(target)
        with open(target, "w") as handle:
            handle.write(self.client.payloads.pop(0) if self.client.payloads else "ok")
        return target


class _FakeClient:
    """Stand-in for ecmwf.datastores.Client that scripts job outcomes.

    ``outcomes`` is consumed one entry per submit: a status string, or a
    (status, message) pair.
    """

    def __init__(self, outcomes=("successful",), started=True, existing=None):
        self.outcomes = list(outcomes)
        self.started = started
        self.submits = []
        self.deleted = []
        self.downloads = []
        self.payloads = []
        self.active = set()
        self.max_active = 0
        self.remotes = dict(existing or {})
        self.active.update(self.remotes)

    def submit(self, collection_id, request):
        outcome = self.outcomes.pop(0)
        status, message = outcome if isinstance(outcome, tuple) else (outcome, "")
        request_id = f"job-{len(self.submits) + 1}"
        self.submits.append((collection_id, request))
        self.active.add(request_id)
        self.max_active = max(self.max_active, len(self.active))
        remote = _FakeRemote(self, request_id, status, message, self.started)
        self.remotes[request_id] = remote
        return remote

    def get_remote(self, request_id):
        return self.remotes[request_id]

    def delete(self, *request_ids):
        for request_id in request_ids:
            self.deleted.append(request_id)
            self.active.discard(request_id)
        return {}


def _always_passes(path):
    return True, ""


def _write_state(target, request_id, saved_request):
    state_path = target.parent / cds_requests.STATE_FILE_NAME
    state_path.write_text(
        json.dumps(
            {
                target.name: {
                    "request_id": request_id,
                    "request_hash": request_hash(DATASET, saved_request),
                }
            }
        )
    )


def _run(client, target, sleeps=None, **kwargs):
    kwargs.setdefault("finalize", check_then_rename(_always_passes, target))
    return run_request(
        DATASET,
        REQUEST,
        target,
        client=client,
        sleep=(sleeps.append if sleeps is not None else lambda seconds: None),
        **kwargs,
    )


def test_successful_job_downloads_to_temp_then_renames_to_target(tmp_path):
    client = _FakeClient()
    target = tmp_path / "tp_2026.grib"

    _run(client, target)

    assert client.submits == [(DATASET, REQUEST)]
    assert len(client.downloads) == 1
    temp_path = client.downloads[0]
    assert str(temp_path) != str(target)
    assert str(temp_path).startswith(str(tmp_path))
    assert target.read_text() == "ok"
    assert [p.name for p in tmp_path.iterdir() if p.name != target.name] == [
        cds_requests.STATE_FILE_NAME
    ]
    assert json.loads((tmp_path / cds_requests.STATE_FILE_NAME).read_text()) == {}


def test_matching_saved_job_is_reattached_without_a_new_submit(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=[])
    client.remotes["old-job"] = _FakeRemote(client, "old-job", "successful")
    _write_state(target, "old-job", REQUEST)

    _run(client, target)

    assert client.submits == []
    assert client.deleted == []
    assert target.read_text() == "ok"


def test_stale_saved_job_is_deleted_before_the_new_submit(tmp_path):
    target = tmp_path / "tp_2026.grib"
    yesterday = dict(REQUEST, day=["01", "02"])
    client = _FakeClient()
    client.remotes["old-job"] = _FakeRemote(client, "old-job", "running")
    client.active.add("old-job")
    _write_state(target, "old-job", yesterday)

    _run(client, target)

    assert client.deleted == ["old-job"]
    assert client.submits == [(DATASET, REQUEST)]
    assert client.max_active == 1
    assert target.exists()


def test_rejected_job_is_submitted_once_and_raises_with_cds_message(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=[("rejected", "day 31 is not valid for month 11")])

    with pytest.raises(RequestRejectedError, match="day 31 is not valid"):
        _run(client, target)

    assert len(client.submits) == 1
    assert not target.exists()


def test_failed_job_is_resubmitted_with_growing_waits(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=["failed", "failed", "successful"])
    sleeps = []

    _run(client, target, sleeps=sleeps, max_attempts=4, backoff_seconds=10)

    assert len(client.submits) == 3
    assert sleeps == [10, 20]
    assert target.exists()


def test_job_failing_every_attempt_raises_and_leaves_no_target(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=["failed"] * 3)

    with pytest.raises(RuntimeError):
        _run(client, target, max_attempts=3)

    assert len(client.submits) == 3
    assert not target.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [cds_requests.STATE_FILE_NAME]


def test_download_failing_the_check_is_deleted_and_retried(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=["successful", "successful"])
    client.payloads = ["truncated", "complete"]

    def check(path):
        content = path.read_text()
        return content == "complete", f"content was {content!r}"

    _run(client, target, finalize=check_then_rename(check, target))

    assert len(client.submits) == 2
    assert target.read_text() == "complete"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [target.name, cds_requests.STATE_FILE_NAME]
    )


def test_check_failure_on_every_attempt_never_creates_target(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient(outcomes=["successful"] * 2)

    with pytest.raises(OutputCheckError, match="wrong dates"):
        _run(
            client,
            target,
            max_attempts=2,
            finalize=check_then_rename(lambda path: (False, "wrong dates"), target),
        )

    assert not target.exists()


def test_transport_error_while_waiting_reattaches_instead_of_resubmitting(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient()
    original_submit = client.submit

    def submit_then_drop_connection(collection_id, request):
        remote = original_submit(collection_id, request)
        status_calls = []

        class _Flaky(type(remote)):
            @property
            def status(self):
                status_calls.append(1)
                if len(status_calls) == 1:
                    raise requests.ConnectionError("connection reset")
                return super().status

        remote.__class__ = _Flaky
        return remote

    client.submit = submit_then_drop_connection

    _run(client, target)

    assert len(client.submits) == 1
    assert target.exists()


def _http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Client Error", response=response)


def test_client_error_at_submit_is_not_retried(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient()

    def bad_submit(collection_id, request):
        client.submits.append((collection_id, request))
        raise _http_error(400)

    client.submit = bad_submit

    with pytest.raises(requests.HTTPError):
        _run(client, target, max_attempts=3)

    assert len(client.submits) == 1


def test_client_error_on_saved_job_clears_it_for_the_next_run(tmp_path):
    target = tmp_path / "tp_2026.grib"
    client = _FakeClient()
    _write_state(target, "expired-job", REQUEST)

    def expired(request_id):
        raise _http_error(404)

    client.get_remote = expired

    with pytest.raises(requests.HTTPError):
        _run(client, target)

    state = json.loads((tmp_path / cds_requests.STATE_FILE_NAME).read_text())
    assert state == {}


def test_three_requests_in_a_row_never_overlap(tmp_path):
    client = _FakeClient(outcomes=["successful"] * 3)

    for name in ("a.grib", "b.grib", "c.grib"):
        _run(client, tmp_path / name)

    assert len(client.submits) == 3
    assert client.max_active == 1


def test_finalize_can_install_several_files_from_one_download(tmp_path):
    client = _FakeClient()
    target = tmp_path / "bundle.zip"
    produced = []

    def split(temp_path):
        for name in ("swe.nc", "swvl1.nc"):
            (tmp_path / name).write_text(temp_path.read_text())
            produced.append(name)

    _run(client, target, finalize=split)

    assert sorted(produced) == ["swe.nc", "swvl1.nc"]
    assert (tmp_path / "swe.nc").read_text() == "ok"
    assert not target.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["swe.nc", "swvl1.nc", cds_requests.STATE_FILE_NAME]
    )


def test_timing_line_reports_queue_and_run_time(tmp_path, caplog):
    client = _FakeClient()
    target = tmp_path / "tp_2026.grib"

    with caplog.at_level(logging.INFO, logger="cds_requests"):
        _run(client, target)

    [line] = [r.getMessage() for r in caplog.records if "queue=" in r.getMessage()]
    assert DATASET in line
    assert str(target) in line
    assert "queue=30.0s" in line
    assert "run=70.0s" in line
    assert "transfer=" in line
    assert "cache_hit=False" in line


def test_timing_line_marks_job_without_start_as_cache_hit(tmp_path, caplog):
    client = _FakeClient(started=False)
    target = tmp_path / "tp_2026.grib"

    with caplog.at_level(logging.INFO, logger="cds_requests"):
        _run(client, target)

    [line] = [r.getMessage() for r in caplog.records if "cache_hit=" in r.getMessage()]
    assert "cache_hit=True" in line
