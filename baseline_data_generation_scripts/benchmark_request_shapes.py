#!/usr/bin/env python3
"""Compare yearly and monthly CDS request shapes for the ERA5-Land climatology.

A sample year is fetched in both shapes, then the following year again in both
shapes, interleaved so that swings in the CDS queue over the day hit both:
yearly, then 12 monthly, then yearly, then 12 monthly. The second round uses a
different year so CDS cannot answer it from its cache of the first round. Each
shape requests its variables as the climatology job would: combined per
dataset, except that a yearly daily-statistics request holds one variable
(CDS refuses three variables over a whole year). Every request goes through
the sequential request runner, one at a time.

Downloads go to a scratch directory, never the climatology directories. The
markdown report lists, per request, the time queued and running at CDS (from
the CDS job record), the local transfer time, and the total wall time, then
the total per shape per round and the verdict: monthly only if its total is
lower in both rounds, otherwise yearly. Requests served from the CDS cache are
flagged, because they make a shape look faster than it is.

    uv run --frozen python -m baseline_data_generation_scripts.benchmark_request_shapes --year 2000
"""

import argparse
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cds_requests import run_request
from config import BASELINE_DATA_ROOT
from download_helpers import (
    _ALL_DAYS,
    _ALL_MONTHS,
    api_credentials_check,
    build_cds_request,
    bundle_suffix,
    group_variables_by_dataset,
    variable_groups_per_request,
)
from file_helpers import setup_logging

logger = logging.getLogger(__name__)

SHAPES = ("yearly", "monthly")
ROUNDS = (1, 2)
DEFAULT_REPORT = Path(__file__).with_name("request_shape_benchmark.md")
DEFAULT_OUTPUT_DIR = BASELINE_DATA_ROOT / "request_shape_benchmark"


@dataclass(frozen=True)
class BenchmarkRequest:
    round: int
    shape: str
    dataset: str
    variable_keys: tuple[str, ...]
    year: int
    months: tuple[str, ...]

    def cds_request(self) -> dict:
        return build_cds_request(
            self.dataset, self.variable_keys, self.year, list(self.months), _ALL_DAYS
        )

    def label(self) -> str:
        months = "all" if len(self.months) == 12 else self.months[0]
        variables = "-".join(self.variable_keys)
        return (
            f"round{self.round}_{self.shape}_{self.dataset}_{variables}"
            f"_{self.year}_{months}"
        )

    def target(self, output_dir: Path) -> Path:
        return Path(output_dir) / f"{self.label()}{bundle_suffix(self.dataset)}"


@dataclass
class Timing:
    request: BenchmarkRequest
    queue: float | None
    run: float | None
    transfer: float | None
    total: float
    cache_hit: bool


def plan_benchmark(year: int) -> list[BenchmarkRequest]:
    """Requests in the order sent: per round, the yearly shape then the
    monthly shape, each covering both datasets with variables combined (one
    daily-statistics variable per yearly request, for the CDS cost limit).

    Each round uses its own year (the sample year, then the year after), so a
    later round never repeats an earlier request that CDS could serve from
    its cache."""
    groups = group_variables_by_dataset()
    plan = []
    for offset, round_ in enumerate(ROUNDS):
        round_year = year + offset
        for dataset, keys in groups.items():
            for group in variable_groups_per_request(dataset, keys, 12):
                plan.append(
                    BenchmarkRequest(
                        round_,
                        "yearly",
                        dataset,
                        group,
                        round_year,
                        tuple(_ALL_MONTHS),
                    )
                )
        for month in _ALL_MONTHS:
            for dataset, keys in groups.items():
                plan.append(
                    BenchmarkRequest(
                        round_, "monthly", dataset, tuple(keys), round_year, (month,)
                    )
                )
    return plan


def choose_request_shape(totals: dict[int, dict[str, float]]) -> str:
    """'monthly' only if the monthly total is lower than the yearly total in
    every round; otherwise 'yearly'."""
    if all(by_shape["monthly"] < by_shape["yearly"] for by_shape in totals.values()):
        return "monthly"
    return "yearly"


class _TimingCapture(logging.Handler):
    """Collect the timing line the request runner logs after each request."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        if record.msg.startswith("CDS request dataset="):
            self.records.append(record.args)


@contextmanager
def _capture_timings():
    runner_logger = logging.getLogger("cds_requests")
    capture = _TimingCapture()
    previous_level = runner_logger.level
    runner_logger.addHandler(capture)
    runner_logger.setLevel(logging.INFO)
    try:
        yield capture
    finally:
        runner_logger.removeHandler(capture)
        runner_logger.setLevel(previous_level)


def _parse_seconds(value: str) -> float | None:
    return None if value == "n/a" else float(value.rstrip("s"))


def run_benchmark(year: int, output_dir: Path, *, client=None) -> list[Timing]:
    """Send every benchmark request in order and time each one."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with _capture_timings() as capture:
        for request in plan_benchmark(year):
            target = request.target(output_dir)
            logger.info("Benchmark request %s", request.label())
            capture.records.clear()
            start = time.monotonic()
            run_request(
                request.dataset,
                request.cds_request(),
                target,
                lambda path, target=target: path.replace(target),
                client=client,
            )
            total = time.monotonic() - start
            _, _, queue, run, transfer, cache_hit = capture.records[-1]
            rows.append(
                Timing(
                    request,
                    _parse_seconds(queue),
                    _parse_seconds(run),
                    _parse_seconds(transfer),
                    total,
                    bool(cache_hit),
                )
            )
    return rows


def shape_totals(rows: list[Timing]) -> dict[int, dict[str, float]]:
    totals = {round_: {shape: 0.0 for shape in SHAPES} for round_ in ROUNDS}
    for row in rows:
        totals[row.request.round][row.request.shape] += row.total
    return totals


def _fmt(seconds: float | None) -> str:
    return "n/a" if seconds is None else f"{seconds:.1f}"


def render_report(year: int, rows: list[Timing]) -> str:
    totals = shape_totals(rows)
    verdict = choose_request_shape(totals)
    cache_hits = sum(row.cache_hit for row in rows)
    lines = [
        "# Climatology request-size benchmark",
        "",
        f"Sample years: {year} (round 1) and {year + 1} (round 2). "
        "Variables combined per dataset; requests sent one "
        "at a time in the order listed. Times in seconds. Queue and run come from "
        "the CDS job record; transfer is timed locally; total is the wall time "
        "of the whole request, including polling.",
        "",
        f"## Verdict: {verdict}",
        "",
        "Monthly requests are chosen only if their total is lower in both rounds.",
        "",
    ]
    if cache_hits:
        lines += [
            f"**{cache_hits} of {len(rows)} requests were served from the CDS "
            "cache** (no start time at CDS). Cached requests skip the queue, so "
            "a round with cache hits flatters whichever shape they fell on.",
            "",
        ]
    lines += [
        "## Totals per round",
        "",
        "| Round | Yearly total | Monthly total | Lower |",
        "| --- | --- | --- | --- |",
    ]
    for round_, by_shape in totals.items():
        lower = min(SHAPES, key=lambda shape: by_shape[shape])
        lines.append(
            f"| {round_} | {_fmt(by_shape['yearly'])} | "
            f"{_fmt(by_shape['monthly'])} | {lower} |"
        )
    lines += [
        "",
        "## Requests",
        "",
        "| Round | Shape | Dataset | Months | Queue | Run | Transfer | Total | Cache hit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        request = row.request
        months = "01-12" if len(request.months) == 12 else request.months[0]
        lines.append(
            f"| {request.round} | {request.shape} | {request.dataset} | {months} | "
            f"{_fmt(row.queue)} | {_fmt(row.run)} | {_fmt(row.transfer)} | "
            f"{_fmt(row.total)} | {'yes' if row.cache_hit else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2000,
        help="Sample year for round 1; round 2 uses the next year.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Scratch directory for the downloads (not a climatology directory).",
    )
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT, help="Markdown report path."
    )
    args = parser.parse_args()

    setup_logging()
    api_credentials_check()
    rows = run_benchmark(args.year, args.output_dir)
    args.report.write_text(render_report(args.year, rows))
    logger.info("Wrote %s", args.report)


if __name__ == "__main__":
    main()
