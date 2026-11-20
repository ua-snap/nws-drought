"""Tests for the CDS request builders, the combined-request split and the
monthly recurring download.

Nothing here contacts CDS: downloads come from fake clients that write
synthetic GRIB, netCDF or zip content.
"""

import datetime
import functools
import json
import zipfile

import eccodes
import numpy as np
import pytest
import xarray as xr

import download_helpers
from cds_requests import STATE_FILE_NAME, OutputCheckError, request_hash
from download_helpers import (
    _ACCUMULATION_FOR_PRIOR_24HRS,
    _ALL_DAYS,
    _ALL_MONTHS,
    _HOURLY_GRIB_ENDPOINT,
    _PREBAKED_DAILY_ENDPOINT,
    _build_hourly_grib_request,
    _build_prebaked_daily_request,
    coverage_months,
    download_recurring_era5_land,
    group_variables_by_dataset,
    month_dates,
    monthly_file_path,
    plan_recurring_requests,
    recurring_monthly_files,
    split_months_then_install,
    split_then_install,
)
from config import DL_BBOX
from file_helpers import GRIB_BACKEND_KWARGS
from file_helpers import check_output_file as _real_check


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


# --- Monthly recurring download -------------------------------------------

HOURLY = _HOURLY_GRIB_ENDPOINT
DAILY = _PREBAKED_DAILY_ENDPOINT
CDS_TO_SHORT_NAME = {
    meta["cds_variable"]: meta["short_name"]
    for meta in download_helpers.VARIABLE_REGISTRY.values()
}


@pytest.fixture
def recent_root(monkeypatch, tmp_path):
    root = tmp_path / "recent_data"
    monkeypatch.setattr(download_helpers, "RECENT_DATA_ROOT", root)
    return root


@pytest.fixture
def older_months_pass(monkeypatch):
    """Treat every monthly file that does not exist as present and passing, so a
    plan reflects only the current month and the re-download window. Files that
    do exist are checked for real."""
    real_check = download_helpers.check_output_file

    def check(path, short_name, expected_dates):
        if not path.exists():
            return True, "assumed present"
        return real_check(path, short_name, expected_dates)

    monkeypatch.setattr(download_helpers, "check_output_file", check)


def _summary(requests):
    """{(dataset, year, months, first requested day, last requested day)}"""
    return {(r.dataset, r.year, r.months, r.days[0], r.days[-1]) for r in requests}


def test_coverage_runs_from_january_of_the_previous_year_to_the_analysis_month():
    months = coverage_months(datetime.date(2026, 11, 18))
    assert months[0] == (2025, 1)
    assert months[-1] == (2026, 11)
    assert len(months) == 23


def test_monthly_file_is_named_by_year_and_month_in_the_recent_dir(recent_root):
    assert monthly_file_path("tp", 2026, 3) == (
        recent_root / "era5_land_daily_tp" / "total_precipitation_daily_2026-03.grib"
    )
    assert monthly_file_path("swvl1", 2025, 12) == (
        recent_root
        / "era5_land_daily_swvl1"
        / "volumetric_soil_water_level_1_daily_2025-12.nc"
    )


def test_recurring_monthly_files_list_every_coverage_month_in_order(recent_root):
    files = recurring_monthly_files("swe", datetime.date(2026, 2, 3))
    assert [f.name for f in files] == [
        f"snow_water_equivalent_daily_2025-{m:02d}.nc" for m in range(1, 13)
    ] + [
        "snow_water_equivalent_daily_2026-01.nc",
        "snow_water_equivalent_daily_2026-02.nc",
    ]


def test_month_dates_cover_the_whole_month_or_stop_at_the_given_day():
    assert month_dates(2026, 2)[-1] == "2026-02-28"
    assert len(month_dates(2026, 2)) == 28
    assert month_dates(2026, 11, last_day=18) == [
        f"2026-11-{d:02d}" for d in range(1, 19)
    ]


def test_steady_state_run_requests_current_month_and_three_month_window(
    recent_root, older_months_pass
):
    # The analysis date moves to 2026-11-18 with January 2025 through
    # October 2026 already on disk: only November and August-October are sent.
    requests = plan_recurring_requests(datetime.date(2026, 11, 18))
    assert len(requests) == 4
    assert _summary(requests) == {
        (HOURLY, 2026, (11,), "01", "18"),
        (DAILY, 2026, (11,), "01", "18"),
        (HOURLY, 2026, (8, 9, 10), "01", "31"),
        (DAILY, 2026, (8, 9, 10), "01", "31"),
    }
    by_dataset = {r.dataset: r.variable_keys for r in requests}
    assert by_dataset == {HOURLY: ("tp", "pev"), DAILY: ("swe", "swvl1", "swvl2")}


def test_first_december_run_requests_december_and_september_to_november(
    recent_root, older_months_pass
):
    requests = plan_recurring_requests(datetime.date(2026, 12, 2))
    assert _summary(requests) == {
        (HOURLY, 2026, (12,), "01", "02"),
        (DAILY, 2026, (12,), "01", "02"),
        (HOURLY, 2026, (9, 10, 11), "01", "31"),
        (DAILY, 2026, (9, 10, 11), "01", "31"),
    }
    december = next(r for r in requests if r.dataset == HOURLY and r.months == (12,))
    # The 00:00 value on December 1 is November 30's total; it is requested
    # inside the December request, with the day list unchanged.
    request = december.cds_request()
    assert request["month"] == ["12"]
    assert request["day"] == ["01", "02"]
    assert request["time"] == "00:00"


def test_window_crossing_new_year_splits_into_one_request_per_year(
    recent_root, older_months_pass
):
    requests = plan_recurring_requests(datetime.date(2027, 2, 10))
    assert len(requests) == 6
    assert _summary(requests) == {
        (HOURLY, 2027, (2,), "01", "10"),
        (DAILY, 2027, (2,), "01", "10"),
        (HOURLY, 2026, (11, 12), "01", "31"),
        (DAILY, 2026, (11, 12), "01", "31"),
        (HOURLY, 2027, (1,), "01", "31"),
        (DAILY, 2027, (1,), "01", "31"),
    }


def test_month_failing_the_check_joins_the_backfill_for_its_year(
    recent_root, older_months_pass, caplog
):
    # A transfer cut off mid-file leaves a March 2026 precipitation file that
    # will not open.
    broken = monthly_file_path("tp", 2026, 3)
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"GRIB\x00\x00")

    with caplog.at_level("INFO", logger="download_helpers"):
        requests = plan_recurring_requests(datetime.date(2026, 11, 18))

    backfill = [r for r in requests if r.months == (3,)]
    assert len(backfill) == 1
    assert backfill[0].dataset == HOURLY
    assert backfill[0].year == 2026
    # Every variable of that dataset is re-requested for the month.
    assert backfill[0].variable_keys == ("tp", "pev")
    assert backfill[0].days == tuple(_ALL_DAYS)
    assert len(requests) == 5
    assert any(
        "total_precipitation_daily_2026-03.grib" in record.getMessage()
        and "replace" in record.getMessage()
        for record in caplog.records
    )


def test_first_run_backfills_each_older_year_within_the_cost_limit(
    recent_root,
):
    requests = plan_recurring_requests(datetime.date(2026, 11, 18))
    assert _summary(requests) == {
        (HOURLY, 2025, tuple(range(1, 13)), "01", "31"),
        (DAILY, 2025, (1, 2, 3, 4), "01", "31"),
        (DAILY, 2025, (5, 6, 7, 8), "01", "31"),
        (DAILY, 2025, (9, 10, 11, 12), "01", "31"),
        (HOURLY, 2026, tuple(range(1, 8)), "01", "31"),
        (DAILY, 2026, (1, 2, 3, 4), "01", "31"),
        (DAILY, 2026, (5, 6, 7), "01", "31"),
        (HOURLY, 2026, (8, 9, 10), "01", "31"),
        (DAILY, 2026, (8, 9, 10), "01", "31"),
        (HOURLY, 2026, (11,), "01", "18"),
        (DAILY, 2026, (11,), "01", "18"),
    }


def test_no_daily_statistics_request_passes_the_cds_cost_limit(recent_root):
    # CDS refused swe, swvl1 and swvl2 for all of 2025 in one request ("cost
    # limits exceeded"); one variable for a whole year is the largest
    # accepted.
    for analysis_date in (datetime.date(2026, 11, 18), datetime.date(2027, 2, 10)):
        for request in plan_recurring_requests(analysis_date):
            if request.dataset == DAILY:
                assert len(request.variable_keys) * len(request.months) <= 12


def test_every_coverage_month_is_requested_once_and_nothing_outside_it(
    recent_root,
):
    # First runs (nothing on disk) request the most; check a date in every
    # month of two years, including year boundaries.
    for year in (2026, 2027):
        for month in range(1, 13):
            analysis_date = datetime.date(year, month, 1 + month)
            covered = set(coverage_months(analysis_date))
            requests = plan_recurring_requests(analysis_date)
            for dataset in (HOURLY, DAILY):
                requested = [
                    (r.year, m)
                    for r in requests
                    if r.dataset == dataset
                    for m in r.months
                ]
                assert sorted(requested) == sorted(covered), analysis_date


# Synthetic CDS -------------------------------------------------------------


def _grib_message(short_name, date, values):
    handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib1")
    try:
        eccodes.codes_set(handle, "shortName", short_name)
        eccodes.codes_set(handle, "dataDate", int(date.strftime("%Y%m%d")))
        eccodes.codes_set(handle, "dataTime", 0)
        eccodes.codes_set_values(handle, values)
        return eccodes.codes_get_message(handle)
    finally:
        eccodes.codes_release(handle)


def _grib_size():
    handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib1")
    size = eccodes.codes_get(handle, "numberOfValues")
    eccodes.codes_release(handle)
    return size


def _write_grib(path, short_names, dates, seed=0):
    """Write one message per (date, variable), interleaved like a CDS download."""
    rng = np.random.default_rng(seed)
    size = _grib_size()
    with open(path, "wb") as f:
        for date in dates:
            for short_name in short_names:
                f.write(_grib_message(short_name, date, rng.random(size) * 0.01))


def _daily_dataset(short_name, dates, packed=False, seed=0):
    """A daily-mean variable shaped like a CDS daily-statistics netCDF."""
    rng = np.random.default_rng(seed)
    values = rng.random((len(dates), 3, 4)).astype("float32")
    values[0, 0, 0] = np.nan
    ds = xr.Dataset(
        {short_name: (("valid_time", "latitude", "longitude"), values)},
        coords={
            "valid_time": np.array(dates, dtype="datetime64[ns]"),
            "latitude": [62.0, 61.0, 60.0],
            "longitude": [-150.0, -149.9, -149.8, -149.7],
        },
    )
    ds[short_name].attrs = {"units": "m", "long_name": short_name}
    encoding = {"_FillValue": np.float32(np.nan), "zlib": True, "complevel": 1}
    if packed:
        encoding = {
            "dtype": "int16",
            "scale_factor": 1e-4,
            "add_offset": 0.5,
            "_FillValue": np.int16(-32767),
        }
    ds[short_name].encoding = encoding
    ds["valid_time"].encoding = {
        "units": "seconds since 1970-01-01",
        "dtype": "int64",
    }
    return ds


def _requested_dates(request):
    """The valid dates CDS returns for a request: only days that exist."""
    dates = []
    for month in request["month"]:
        for day in request["day"]:
            try:
                dates.append(datetime.date(int(request["year"]), int(month), int(day)))
            except ValueError:
                continue
    return dates


class _SyntheticJob:
    def __init__(self, request_id, dataset, request, workdir):
        self.request_id = request_id
        self.dataset = dataset
        self.request = request
        self.workdir = workdir
        self.status = "successful"
        self.created_at = datetime.datetime(2026, 12, 2, 12, 0, 0)
        self.started_at = self.created_at
        self.finished_at = self.created_at

    def download(self, target):
        dates = _requested_dates(self.request)
        short_names = [CDS_TO_SHORT_NAME[v] for v in self.request["variable"]]
        if self.dataset == HOURLY:
            _write_grib(target, short_names, dates)
            return target
        members = self.workdir / self.request_id
        members.mkdir(parents=True)
        with zipfile.ZipFile(target, "w") as zf:
            for short_name in short_names:
                member = members / f"{short_name}.nc"
                _daily_dataset(short_name, [str(d) for d in dates]).to_netcdf(
                    member, engine="h5netcdf"
                )
                zf.write(member, arcname=member.name)
        return target


class _SyntheticCds:
    """Fake datastores client whose jobs finish at once with synthetic data."""

    def __init__(self, workdir):
        self.workdir = workdir
        self.submits = []

    def submit(self, dataset, request):
        self.submits.append((dataset, request))
        return _SyntheticJob(f"job-{len(self.submits)}", dataset, request, self.workdir)

    def get_remote(self, request_id):
        raise AssertionError("no saved jobs expected")

    def delete(self, *request_ids):
        raise AssertionError("no stale jobs expected")


def test_december_run_writes_one_checked_file_per_variable_per_month(
    recent_root, older_months_pass, tmp_path
):
    client = _SyntheticCds(tmp_path / "cds")

    download_recurring_era5_land(datetime.date(2026, 12, 2), client=client)

    assert len(client.submits) == 4
    for key, meta in download_helpers.VARIABLE_REGISTRY.items():
        for month in (9, 10, 11, 12):
            path = monthly_file_path(key, 2026, month)
            expected = month_dates(2026, month, last_day=2 if month == 12 else None)
            ok, reason = download_helpers.check_output_file(
                path, meta["short_name"], expected
            )
            assert ok, reason
    with xr.open_dataset(
        monthly_file_path("tp", 2026, 11),
        engine="cfgrib",
        backend_kwargs=GRIB_BACKEND_KWARGS,
    ) as ds:
        assert str(ds["valid_time"].values[-1])[:10] == "2026-11-30"
    with xr.open_dataset(
        monthly_file_path("tp", 2026, 12),
        engine="cfgrib",
        backend_kwargs=GRIB_BACKEND_KWARGS,
    ) as ds:
        assert [str(t)[:10] for t in ds["valid_time"].values] == [
            "2026-12-01",
            "2026-12-02",
        ]
    # Older months were reused, so nothing was written for them.
    assert not monthly_file_path("tp", 2026, 8).exists()


# Splitting a multi-month download --------------------------------------------

TWO_MONTH_DATES = [datetime.date(2026, 2, d) for d in range(1, 29)] + [
    datetime.date(2026, 3, d) for d in range(1, 32)
]
FEB_MAR = [(2026, 2), (2026, 3)]


def _month_targets(root, short_names, suffix):
    return {
        name: {
            (y, m): root / f"{name}_dir" / f"{name}_{y}-{m:02d}{suffix}"
            for y, m in FEB_MAR
        }
        for name in short_names
    }


def _expected_by_month():
    return {(y, m): month_dates(y, m) for y, m in FEB_MAR}


def test_multi_month_grib_splits_into_byte_identical_monthly_files(tmp_path):
    bundle = tmp_path / "bundle.partial.grib"
    _write_grib(bundle, ["tp", "pev"], TWO_MONTH_DATES)
    source = _raw_messages(bundle)
    targets = _month_targets(tmp_path, ["tp", "pev"], ".grib")

    split_months_then_install(targets, _expected_by_month())(bundle)

    for name, by_month in targets.items():
        rebuilt = []
        for (year, month), path in by_month.items():
            ok, reason = download_helpers.check_output_file(
                path, name, month_dates(year, month)
            )
            assert ok, reason
            rebuilt += _raw_messages(path)
        # Every message of this variable, copied byte for byte and in order.
        expected = [
            raw for i, raw in enumerate(source) if (i % 2 == 0) == (name == "tp")
        ]
        assert rebuilt == expected
    assert not [p for p in tmp_path.rglob("*") if ".split" in p.name]


@pytest.mark.parametrize("packed", [False, True])
def test_multi_month_netcdf_split_keeps_stored_and_decoded_values(tmp_path, packed):
    dates = [str(d) for d in TWO_MONTH_DATES]
    work = tmp_path / "members"
    work.mkdir()
    bundle = tmp_path / "bundle.partial.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        for i, name in enumerate(["sd", "swvl1", "swvl2"]):
            _daily_dataset(name, dates, packed=packed, seed=i).to_netcdf(
                work / f"{name}.nc", engine="h5netcdf"
            )
            zf.write(work / f"{name}.nc", arcname=f"{name}.nc")
    targets = _month_targets(tmp_path, ["sd", "swvl1", "swvl2"], ".nc")

    split_months_then_install(targets, _expected_by_month())(bundle)

    for name, by_month in targets.items():
        source_raw = xr.open_dataset(work / f"{name}.nc", decode_cf=False)
        source = xr.open_dataset(work / f"{name}.nc")
        with source_raw, source:
            assert source_raw[name].dtype == ("int16" if packed else "float32")
            for (year, month), path in by_month.items():
                in_month = (source["valid_time"].dt.month.values == month).nonzero()[0]
                split_raw = xr.open_dataset(path, decode_cf=False)
                split = xr.open_dataset(path)
                with split_raw, split:
                    # Stored numbers, their dtype and packing attributes are
                    # unchanged...
                    xr.testing.assert_identical(
                        split_raw[name], source_raw[name].isel(valid_time=in_month)
                    )
                    assert split_raw[name].dtype == source_raw[name].dtype
                    # ...so the values the pipeline decodes are unchanged too.
                    xr.testing.assert_identical(
                        split[name], source[name].isel(valid_time=in_month)
                    )


def test_multi_month_split_missing_a_day_installs_no_month(tmp_path):
    bundle = tmp_path / "bundle.partial.grib"
    _write_grib(bundle, ["tp", "pev"], TWO_MONTH_DATES[:-1])
    targets = _month_targets(tmp_path, ["tp", "pev"], ".grib")

    with pytest.raises(OutputCheckError, match="dates differ"):
        split_months_then_install(targets, _expected_by_month())(bundle)

    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p != bundle]


def test_multi_month_split_missing_a_variable_installs_nothing(tmp_path):
    bundle = tmp_path / "bundle.partial.grib"
    _write_grib(bundle, ["tp"], TWO_MONTH_DATES)
    targets = _month_targets(tmp_path, ["tp", "pev"], ".grib")

    with pytest.raises(OutputCheckError, match="pev"):
        split_months_then_install(targets, _expected_by_month())(bundle)

    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p != bundle]


def test_second_download_run_in_the_same_directory_stops_before_submitting(tmp_path):
    with download_helpers.exclusive_download_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already running"):
            with download_helpers.exclusive_download_lock(tmp_path):
                pass
    # released when the first run ends
    with download_helpers.exclusive_download_lock(tmp_path):
        pass
