"""Tests for the CDS request builders and pipeline date-window propagation.

Regression coverage for the bug where the hourly GRIB (accumulation) request
builder ignored the pipeline's computed months/days and requested too many months and days,
sometimes producing identical requests across runs and letting the CDS results cache serve stale data.
"""

import datetime

import pytest

import download_helpers
from download_helpers import (
    _ACCUMULATION_FOR_PRIOR_24HRS,
    _ALL_DAYS,
    _ALL_MONTHS,
    _HOURLY_GRIB_ENDPOINT,
    _PREBAKED_DAILY_ENDPOINT,
    _build_hourly_grib_request,
    _build_prebaked_daily_request,
    analysis_date_not_in_january,
    download_recurring_era5_land_pipeline,
    get_all_previous_year_dates,
    get_current_month_dates,
    get_rest_of_current_year_dates,
)


@pytest.fixture
def freeze_analysis_date(monkeypatch):
    """Return a helper that makes get_analysis_date() return a fixed date."""

    def _freeze(date: datetime.date):
        # Replace the real date lookup for the duration of the test so
        # date-dependent behavior is deterministic.
        monkeypatch.setattr(download_helpers, "get_analysis_date", lambda: date)

    return _freeze


class _RecordingClient:
    """Stand-in for cdsapi.Client that records retrieve() calls."""

    calls: list

    def __init__(self, *args, **kwargs):
        # Accept the same construction pattern as cdsapi.Client without
        # authenticating or creating a real API client.
        pass

    def retrieve(self, endpoint, request, target=None):
        # Record what the pipeline would have sent to CDS instead of
        # making a network request.
        _RecordingClient.calls.append((endpoint, request, target))


@pytest.fixture
def recorded_downloads(monkeypatch, tmp_path):
    # Reset recorded API calls for each test.
    _RecordingClient.calls = []
    # Replace cdsapi.Client with our fake client so tests never contact CDS.
    monkeypatch.setattr(download_helpers.cdsapi, "Client", _RecordingClient)
    # Bypass the real credentials check
    monkeypatch.setattr(download_helpers, "api_credentials_check", lambda: None)
    # Redirect output paths to pytest's temp directory
    monkeypatch.setattr(download_helpers, "RECENT_DATA_ROOT", tmp_path)
    # Tests can inspect this list to verify the endpoint, request, and target
    # that the pipeline attempted to pass to cdsapi.Client.retrieve().
    return _RecordingClient.calls


def test_hourly_grib_request_uses_given_months_and_days():
    months = ["08"]
    days = ["01", "02", "03"]
    request = _build_hourly_grib_request("total_precipitation", 2026, months, days)
    assert request["year"] == "2026"
    assert request["month"] == months
    assert request["day"] == days
    assert request["time"] == _ACCUMULATION_FOR_PRIOR_24HRS


def test_prebaked_daily_request_uses_given_months_and_days():
    months = ["08"]
    days = ["01", "02", "03"]
    request = _build_prebaked_daily_request(
        "snow_depth_water_equivalent", 2026, months, days
    )
    assert request["year"] == "2026"
    assert request["month"] == months
    assert request["day"] == days
    assert request["daily_statistic"] == "daily_mean"


def test_current_month_days_end_at_analysis_date(freeze_analysis_date):
    # The requested day list ends at the analysis date's day. Because CDS treats
    # the day list as valid times and the 00:00 UTC step on date D is the 24-hr
    # accumulation for D-1, the last downloaded message is labeled with the
    # analysis date and holds the accumulation for the day before it. This
    # matches the climatology convention, so no day-window extension is needed.
    freeze_analysis_date(datetime.date(2026, 8, 13))
    year, month, days = get_current_month_dates()
    assert year == "2026"
    assert month == "08"
    assert days[0] == "01"
    assert days[-1] == "13"
    assert len(days) == 13


def test_current_month_and_current_year_hourly_requests_differ(freeze_analysis_date):
    # Regression: these two requests used to be byte-identical for the sum
    # branch, so CDS treated them as the same (cached) query.
    freeze_analysis_date(datetime.date(2026, 8, 13))
    month_request = _build_hourly_grib_request(
        "total_precipitation", *get_current_month_dates()
    )
    year_request = _build_hourly_grib_request(
        "total_precipitation", *get_rest_of_current_year_dates()
    )
    assert month_request != year_request
    assert month_request["month"] == "08"
    assert year_request["month"] == [f"{m:02d}" for m in range(1, 8)]
    assert year_request["day"] == _ALL_DAYS


def test_current_month_request_varies_with_analysis_date(freeze_analysis_date):
    # The request must change from one run to the next so the CDS results
    # cache key changes and stale cache hits cannot occur.
    freeze_analysis_date(datetime.date(2026, 8, 13))
    request_a = _build_hourly_grib_request(
        "total_precipitation", *get_current_month_dates()
    )
    freeze_analysis_date(datetime.date(2026, 8, 14))
    request_b = _build_hourly_grib_request(
        "total_precipitation", *get_current_month_dates()
    )
    assert request_a != request_b
    assert request_b["day"][-1] == "14"


def test_previous_year_dates_roll_over_january(freeze_analysis_date):
    freeze_analysis_date(datetime.date(2026, 1, 5))
    assert analysis_date_not_in_january() is False
    year, months, days = get_all_previous_year_dates()
    assert year == "2025"
    assert months == _ALL_MONTHS
    assert days == _ALL_DAYS
    _, month, month_days = get_current_month_dates()
    assert month == "01"
    assert month_days == ["01", "02", "03", "04", "05"]


def test_pipeline_sum_branch_forwards_months_and_days(recorded_downloads):
    months = ["08"]
    days = ["01", "02", "03"]
    download_recurring_era5_land_pipeline("tp", "current_month", 2026, months, days)
    endpoint, request, target = recorded_downloads[0]
    assert endpoint == _HOURLY_GRIB_ENDPOINT
    assert request["month"] == months
    assert request["day"] == days
    assert target.name == "total_precipitation_daily_current_month.grib"


def test_pipeline_mean_branch_forwards_months_and_days(recorded_downloads):
    months = ["08"]
    days = ["01", "02", "03"]
    download_recurring_era5_land_pipeline("swe", "current_month", 2026, months, days)
    endpoint, request, target = recorded_downloads[0]
    assert endpoint == _PREBAKED_DAILY_ENDPOINT
    assert request["month"] == months
    assert request["day"] == days
    assert target.name == "snow_water_equivalent_daily_current_month.nc"
