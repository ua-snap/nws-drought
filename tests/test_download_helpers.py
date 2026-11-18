"""Tests for the CDS request builders and pipeline date-window propagation.

Regression coverage for the bug where the hourly GRIB (accumulation) request
builder ignored the pipeline's computed months/days and requested too many months and days,
sometimes producing identical requests across runs and letting the CDS results cache serve stale data.
"""

import datetime
import zipfile

import eccodes
import numpy as np
import pytest
import xarray as xr

import download_helpers
from cds_requests import OutputCheckError
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
    group_variables_by_dataset,
    split_then_install,
)
from config import DL_BBOX
from file_helpers import GRIB_BACKEND_KWARGS


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
    request = _build_hourly_grib_request(["total_precipitation"], 2026, months, days)
    assert request["year"] == "2026"
    assert request["month"] == months
    assert request["day"] == days
    assert request["time"] == _ACCUMULATION_FOR_PRIOR_24HRS


def test_prebaked_daily_request_uses_given_months_and_days():
    months = ["08"]
    days = ["01", "02", "03"]
    request = _build_prebaked_daily_request(
        ["snow_depth_water_equivalent"], 2026, months, days
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
        ["total_precipitation"], *get_current_month_dates()
    )
    year_request = _build_hourly_grib_request(
        ["total_precipitation"], *get_rest_of_current_year_dates()
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
        ["total_precipitation"], *get_current_month_dates()
    )
    freeze_analysis_date(datetime.date(2026, 8, 14))
    request_b = _build_hourly_grib_request(
        ["total_precipitation"], *get_current_month_dates()
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


MARCH_2026_DAYS = [f"{day:02d}" for day in range(1, 32)]


def test_variables_group_by_dataset():
    groups = group_variables_by_dataset()
    assert groups == {
        _HOURLY_GRIB_ENDPOINT: ["tp", "pev"],
        _PREBAKED_DAILY_ENDPOINT: ["swe", "swvl1", "swvl2"],
    }


def test_hourly_request_for_march_lists_both_summed_variables():
    cds_variables = [
        download_helpers.VARIABLE_REGISTRY[key]["cds_variable"]
        for key in group_variables_by_dataset()[_HOURLY_GRIB_ENDPOINT]
    ]
    request = _build_hourly_grib_request(cds_variables, 2026, ["03"], MARCH_2026_DAYS)
    assert request == {
        "variable": ["total_precipitation", "potential_evaporation"],
        "year": "2026",
        "month": ["03"],
        "day": MARCH_2026_DAYS,
        "time": "00:00",
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def test_daily_statistics_request_for_march_lists_three_mean_variables():
    cds_variables = [
        download_helpers.VARIABLE_REGISTRY[key]["cds_variable"]
        for key in group_variables_by_dataset()[_PREBAKED_DAILY_ENDPOINT]
    ]
    request = _build_prebaked_daily_request(
        cds_variables, 2026, ["03"], MARCH_2026_DAYS
    )
    assert request == {
        "variable": [
            "snow_depth_water_equivalent",
            "volumetric_soil_water_layer_1",
            "volumetric_soil_water_layer_2",
        ],
        "year": "2026",
        "month": ["03"],
        "day": MARCH_2026_DAYS,
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": DL_BBOX,
    }


FIXTURE_DATES = ["2026-03-01", "2026-03-02", "2026-03-03"]


def _write_two_variable_grib(path):
    """Write tp and pev messages (one per day, interleaved like a CDS download).

    Returns {shortName: [raw message bytes in file order]}."""
    rng = np.random.default_rng(0)
    messages = {"tp": [], "pev": []}
    with open(path, "wb") as f:
        for date in FIXTURE_DATES:
            for short_name in ("tp", "pev"):
                handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib1")
                eccodes.codes_set(handle, "shortName", short_name)
                eccodes.codes_set(handle, "dataDate", int(date.replace("-", "")))
                eccodes.codes_set(handle, "dataTime", 0)
                size = eccodes.codes_get(handle, "numberOfValues")
                eccodes.codes_set_values(handle, rng.random(size) * 0.01)
                raw = eccodes.codes_get_message(handle)
                eccodes.codes_release(handle)
                f.write(raw)
                messages[short_name].append(raw)
    return messages


def _raw_messages(path):
    raws = []
    with open(path, "rb") as f:
        while (handle := eccodes.codes_grib_new_from_file(f)) is not None:
            raws.append(eccodes.codes_get_message(handle))
            eccodes.codes_release(handle)
    return raws


def _grib_targets(tmp_path):
    return {
        "tp": tmp_path / "tp_dir" / "total_precipitation_daily_2026_03.grib",
        "pev": tmp_path / "pev_dir" / "potential_evaporation_daily_2026_03.grib",
    }


def test_grib_split_copies_each_variables_messages_unchanged(tmp_path):
    bundle = tmp_path / "bundle.partial.grib"
    source = _write_two_variable_grib(bundle)
    targets = _grib_targets(tmp_path)

    split_then_install(targets, FIXTURE_DATES)(bundle)

    for short_name, target in targets.items():
        split = _raw_messages(target)
        assert len(split) == len(source[short_name]) == 3
        # Messages are copied byte for byte, so the values cannot change.
        assert split == source[short_name]
        # Decoded values match the same variable read straight from the
        # combined download, as the pipeline would read a one-variable file.
        split_ds = xr.open_dataset(
            target, engine="cfgrib", backend_kwargs=GRIB_BACKEND_KWARGS
        )
        source_ds = xr.open_dataset(
            bundle,
            engine="cfgrib",
            backend_kwargs={
                **GRIB_BACKEND_KWARGS,
                "filter_by_keys": {"shortName": short_name},
            },
        )
        with split_ds, source_ds:
            assert list(split_ds.data_vars) == [short_name]
            assert split_ds[short_name].shape[0] == 3
            xr.testing.assert_identical(split_ds[short_name], source_ds[short_name])
    assert not list(tmp_path.rglob("*.split*"))


def test_grib_missing_a_variable_raises_and_installs_nothing(tmp_path):
    bundle = tmp_path / "bundle.partial.grib"
    _write_two_variable_grib(bundle)
    targets = _grib_targets(tmp_path)
    targets["swvl1"] = tmp_path / "swvl1_dir" / "never.grib"

    with pytest.raises(
        OutputCheckError, match=r"missing expected variables \[.swvl1.\]"
    ):
        split_then_install(targets, FIXTURE_DATES)(bundle)

    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p != bundle]


def _write_daily_netcdf(path, short_name, dates=FIXTURE_DATES):
    ds = xr.Dataset(
        {short_name: (("valid_time", "latitude"), np.ones((len(dates), 2)))},
        coords={
            "valid_time": np.array(dates, dtype="datetime64[ns]"),
            "latitude": [60.0, 61.0],
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")


def _daily_targets(tmp_path):
    return {
        "sd": tmp_path / "swe_dir" / "snow_water_equivalent_daily_2026_03.nc",
        "swvl1": tmp_path / "swvl1_dir" / "volumetric_soil_water_level_1_daily.nc",
        "swvl2": tmp_path / "swvl2_dir" / "volumetric_soil_water_level_2_daily.nc",
    }


def _write_zip(tmp_path, members):
    """members: {member name: short_name written inside it}."""
    work = tmp_path / "members"
    work.mkdir()
    bundle = tmp_path / "bundle.partial.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        for member, short_name in members.items():
            _write_daily_netcdf(work / member, short_name)
            zf.write(work / member, arcname=member)
    return bundle


def test_zip_of_three_netcdfs_moves_each_to_its_target(tmp_path):
    # Member names deliberately do not match their contents: the variable is
    # identified by opening each file.
    bundle = _write_zip(tmp_path, {"a.nc": "swvl2", "b.nc": "sd", "c.nc": "swvl1"})
    targets = _daily_targets(tmp_path)

    split_then_install(targets, FIXTURE_DATES)(bundle)

    for short_name, target in targets.items():
        with xr.open_dataset(target, engine="h5netcdf") as ds:
            assert list(ds.data_vars) == [short_name]


def test_zip_missing_a_variable_raises_and_installs_nothing(tmp_path):
    bundle = _write_zip(tmp_path, {"a.nc": "sd", "b.nc": "swvl1"})
    targets = _daily_targets(tmp_path)

    with pytest.raises(
        OutputCheckError, match=r"missing expected variables \[.swvl2.\]"
    ):
        split_then_install(targets, FIXTURE_DATES)(bundle)

    assert not any(target.exists() for target in targets.values())
    leftovers = [
        p
        for p in tmp_path.rglob("*")
        if p.is_file() and p != bundle and "members" not in p.parts
    ]
    assert leftovers == []


def test_split_file_with_wrong_dates_raises_and_installs_nothing(tmp_path):
    bundle = _write_zip(tmp_path, {"a.nc": "sd", "b.nc": "swvl1", "c.nc": "swvl2"})
    targets = _daily_targets(tmp_path)

    with pytest.raises(OutputCheckError, match="dates differ"):
        split_then_install(targets, FIXTURE_DATES + ["2026-03-04"])(bundle)

    assert not any(target.exists() for target in targets.values())


def test_single_variable_bare_netcdf_is_installed(tmp_path):
    bundle = tmp_path / "bundle.partial.zip"
    _write_daily_netcdf(bundle, "sd")
    target = _daily_targets(tmp_path)["sd"]

    split_then_install({"sd": target}, FIXTURE_DATES)(bundle)

    with xr.open_dataset(target, engine="h5netcdf") as ds:
        assert list(ds.data_vars) == ["sd"]
