"""Tests for the climatology request-size benchmark: the interleaved request
order, the timings taken from each CDS job, and the verdict. Nothing here
contacts CDS."""

import datetime
import json

from baseline_data_generation_scripts import benchmark_request_shapes as bench
from download_helpers import _HOURLY_GRIB_ENDPOINT, _PREBAKED_DAILY_ENDPOINT


def test_monthly_wins_only_when_lower_in_both_rounds():
    totals = {
        1: {"yearly": 100.0, "monthly": 90.0},
        2: {"yearly": 100.0, "monthly": 80.0},
    }
    assert bench.choose_request_shape(totals) == "monthly"


def test_yearly_is_kept_when_monthly_is_lower_in_only_one_round():
    totals = {
        1: {"yearly": 100.0, "monthly": 90.0},
        2: {"yearly": 100.0, "monthly": 120.0},
    }
    assert bench.choose_request_shape(totals) == "yearly"


def test_requests_interleave_yearly_and_monthly_over_two_rounds():
    plan = bench.plan_benchmark(2000)

    assert [(r.round, r.shape) for r in plan] == (
        [(1, "yearly")] * 4
        + [(1, "monthly")] * 24
        + [(2, "yearly")] * 4
        + [(2, "monthly")] * 24
    )
    yearly = [r.cds_request() for r in plan[:4]]
    assert [len(r["month"]) for r in yearly] == [12, 12, 12, 12]
    # CDS refuses three daily-statistics variables over a whole year, so the
    # yearly shape asks for them one at a time.
    assert [r.variable_keys for r in plan[:4]] == [
        ("tp", "pev"),
        ("swe",),
        ("swvl1",),
        ("swvl2",),
    ]
    assert {tuple(r["month"]) for r in (p.cds_request() for p in plan[4:28])} == {
        (f"{m:02d}",) for m in range(1, 13)
    }
    assert {r.dataset for r in plan} == {
        _HOURLY_GRIB_ENDPOINT,
        _PREBAKED_DAILY_ENDPOINT,
    }
    # The second round uses the next year so CDS cannot answer it from the
    # cache filled by the first round's identical requests.
    assert {r.cds_request()["year"] for r in plan if r.round == 1} == {"2000"}
    assert {r.cds_request()["year"] for r in plan if r.round == 2} == {"2001"}
    requests = [json.dumps(r.cds_request(), sort_keys=True) for r in plan]
    assert len(set(requests)) == len(requests)


class _Job:
    def __init__(self, request_id, cached):
        self.request_id = request_id
        self.status = "successful"
        self.created_at = datetime.datetime(2026, 11, 18, 12, 0, 0)
        self.started_at = (
            None if cached else self.created_at + datetime.timedelta(seconds=40)
        )
        self.finished_at = self.created_at + datetime.timedelta(seconds=100)

    def download(self, target):
        open(target, "wb").close()
        return target


class _Client:
    def __init__(self):
        self.submits = []

    def submit(self, dataset, request):
        self.submits.append(dataset)
        # every request after the first round is served from the cache
        return _Job(f"job-{len(self.submits)}", cached=len(self.submits) > 28)


def test_benchmark_records_queue_and_run_time_and_flags_cache_hits(tmp_path):
    rows = bench.run_benchmark(2000, tmp_path, client=_Client())

    assert len(rows) == 56
    first = rows[0]
    assert (first.queue, first.run, first.cache_hit) == (40.0, 60.0, False)
    assert first.transfer is not None and first.total is not None
    assert rows[-1].cache_hit and rows[-1].queue is None
    report = bench.render_report(2000, rows)
    assert "Verdict" in report
    assert "28 of 56 requests were served from the CDS cache" in report
