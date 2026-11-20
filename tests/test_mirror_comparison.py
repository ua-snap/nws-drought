"""Tests for the cloud-mirror comparison: daily rebuilds, difference statistics, and
the no-API-key path. Synthetic arrays only; nothing here touches the network."""

import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import era5_land_mirror
from baseline_data_generation_scripts import compare_era5_land_mirror as mirror


def test_one_packing_step_difference_is_reported_and_not_exact():
    step = 2.0**-20
    times = pd.date_range("2000-01-01", periods=3, freq="D")
    coords = {"valid_time": times, "latitude": [61.0, 60.9], "longitude": [-150.0]}
    cds = xr.DataArray(
        np.full((3, 2, 1), 0.25), dims=("valid_time", "latitude", "longitude")
    ).assign_coords(coords)
    candidate = cds.copy()
    candidate[1, 0, 0] = 0.25 + step

    stats = mirror.compare_values(candidate, cds)

    assert stats["max_abs_diff"] == pytest.approx(step, rel=0, abs=0)
    assert stats["median_abs_diff"] == 0.0
    assert stats["share_equal"] == pytest.approx(5 / 6)
    assert stats["exact_match"] is False
    assert "not an exact match" in mirror.render_variable_row("tp", stats)


def test_identical_arrays_are_an_exact_match():
    times = pd.date_range("2000-01-01", periods=2, freq="D")
    cds = xr.DataArray(
        np.array([[[0.1, np.nan]], [[0.2, np.nan]]]),
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": times, "latitude": [61.0], "longitude": [-150.0, -149.9]},
    )

    stats = mirror.compare_values(cds.copy(), cds)

    assert stats["exact_match"] is True
    assert stats["max_abs_diff"] == 0.0


def test_without_api_key_report_says_not_tested_and_no_remote_open(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(mirror.API_KEY_ENV_VAR, raising=False)

    def _no_network(*args, **kwargs):
        raise AssertionError("remote store must not be opened without an API key")

    monkeypatch.setattr(mirror, "open_mirror_store", _no_network)
    report = tmp_path / "mirror_comparison.md"

    mirror.main(["--year", "2000", "--report", str(report)])

    text = report.read_text()
    assert "not tested" in text
    assert mirror.API_KEY_ENV_VAR in text
    # the untested candidates are still described
    assert "potential evaporation" in text
    assert "24-hour" in text


def test_month_range_and_period_bounds_cover_whole_months():
    assert mirror._month_range("1-3") == (1, 3)
    assert mirror._month_range("2") == (2, 2)
    with pytest.raises(Exception):
        mirror._month_range("3-1")
    assert mirror.period_bounds(2000, (1, 3)) == (
        datetime.date(2000, 1, 1),
        datetime.date(2000, 3, 31),
    )
    assert mirror.period_bounds(2000, (12, 12))[1] == datetime.date(2000, 12, 31)
    # 2000 is a leap year
    assert len(mirror.expected_cds_dates(*mirror.period_bounds(2000, (1, 3)))) == 91


def test_fresh_cds_request_asks_for_one_variable_and_the_chosen_months(
    monkeypatch, tmp_path
):
    sent = []

    def fake_run_request(dataset, request, target, finalize, *, client=None):
        sent.append((dataset, request, target))

    monkeypatch.setattr(mirror, "run_request", fake_run_request)
    start, end = mirror.period_bounds(2000, (1, 3))

    path, seconds = mirror.fetch_cds("swvl1", start, end, tmp_path)

    (dataset, request, bundle), = sent
    assert dataset == "derived-era5-land-daily-statistics"
    assert request["variable"] == ["volumetric_soil_water_layer_1"]
    assert request["year"] == "2000"
    assert request["month"] == ["01", "02", "03"]
    assert bundle.parent == tmp_path and path.parent == tmp_path
    assert seconds is not None and seconds >= 0


def test_cds_file_already_passing_the_check_is_reused_untimed(monkeypatch, tmp_path):
    start, end = mirror.period_bounds(2000, (1, 3))
    existing = mirror.cds_file_path(tmp_path, "swvl1", start, end)
    existing.write_bytes(b"checked elsewhere")
    monkeypatch.setattr(mirror, "check_output_file", lambda *a: (True, ""))

    def no_request(*args, **kwargs):
        raise AssertionError("a passing file must not be requested again")

    monkeypatch.setattr(mirror, "run_request", no_request)

    assert mirror.fetch_cds("swvl1", start, end, tmp_path) == (existing, None)


def test_timed_run_compares_one_variable_and_reports_both_times(
    monkeypatch, tmp_path
):
    days = pd.date_range("2000-01-01", "2000-03-31", freq="D")
    hours = pd.date_range("1999-12-31T00:00", "2000-03-31T23:00", freq="h")
    hourly = xr.DataArray(
        np.full((hours.size, 1, 1), 0.25),
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": hours, "latitude": [61.0], "longitude": [-150.0]},
    )
    cds = hourly.sel(valid_time=days)  # daily means of a constant field
    requested = []

    monkeypatch.setenv(mirror.API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(mirror, "open_mirror_store", lambda key: None)
    monkeypatch.setattr(mirror, "fetch_mirror", lambda store, name, s, e: hourly)

    def fake_fetch_cds(var, start, end, cds_dir, *, client=None):
        requested.append((var, start, end))
        return tmp_path / "cds.nc", 3600.0

    monkeypatch.setattr(mirror, "fetch_cds", fake_fetch_cds)
    monkeypatch.setattr(mirror, "load_cds", lambda path, var, s, e: cds)
    report = tmp_path / "report.md"

    mirror.main(
        ["--year", "2000", "--months", "1-3", "--variable", "swvl1", "--from-cds",
         "--cds-dir", str(tmp_path), "--report", str(report)]
    )

    assert requested == [
        ("swvl1", datetime.date(2000, 1, 1), datetime.date(2000, 3, 31))
    ]
    text = report.read_text()
    assert "2000-01-01 through 2000-03-31" in text
    assert "| exact match |" in text
    assert "| swvl1 |" in text and "| swe |" not in text
    assert "3600.0 s" in text


def test_comparison_names_the_cds_rows_and_columns_the_mirror_lacks():
    times = pd.date_range("2000-01-01", periods=2, freq="D")
    cds = xr.DataArray(
        np.ones((2, 3, 3)),
        dims=("valid_time", "latitude", "longitude"),
        coords={
            "valid_time": times,
            "latitude": [72.0, 71.9, 71.8],
            "longitude": [-180.0, -179.9, -179.8],
        },
    )
    candidate = cds.isel(latitude=slice(1, None), longitude=slice(1, None))

    stats = mirror.compare_values(candidate, cds)

    assert stats["cds_points_unmatched"] == 2 * (9 - 4)
    assert stats["cds_latitudes_unmatched"] == [72.0]
    assert stats["cds_longitudes_unmatched"] == [-180.0]
    assert stats["cds_days_unmatched"] == 0
    grid = "\n".join(mirror.render_grid_alignment({"swvl1": stats}))
    assert "| swvl1 | 1 (72) | 1 (-180) | 0 |" in grid


def test_evaporation_uses_the_form_detected_from_precipitation(monkeypatch, tmp_path):
    # Evaporation running totals that change sign during the day shrink in
    # magnitude, which on their own look like hourly increments. The store's form
    # is read from precipitation and used for evaporation.
    hours = pd.date_range("1999-12-31T00:00", "2000-01-31T23:00", freq="h")
    rng = np.random.default_rng(3)
    since_midnight = (hours.hour.values - 1) % 24 + 1  # 01:00 -> 1 ... 00:00 -> 24
    flux = rng.uniform(-2e-4, 1e-4, size=(hours.size, 1, 1))
    pev_hourly = np.zeros_like(flux)
    for i, step in enumerate(since_midnight):
        pev_hourly[i] = flux[i] if step == 1 else pev_hourly[i - 1] + flux[i]
    increments = rng.uniform(0, 1e-3, size=flux.shape)
    tp_hourly = np.zeros_like(flux)
    for i, step in enumerate(since_midnight):
        tp_hourly[i] = increments[i] if step == 1 else tp_hourly[i - 1] + increments[i]

    def wrap(values):
        return xr.DataArray(
            values,
            dims=("valid_time", "latitude", "longitude"),
            coords={"valid_time": hours, "latitude": [61.0], "longitude": [-150.0]},
        )

    hourly = {"tp": wrap(tp_hourly), "pev": wrap(pev_hourly)}
    assert era5_land_mirror.detect_accumulation_convention(hourly["pev"]) == "increments"

    monkeypatch.setenv(mirror.API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(mirror, "open_mirror_store", lambda key: None)
    def fake_fetch(store, name, s, e):
        return hourly[name].sel(
            valid_time=slice(f"{s - datetime.timedelta(days=1)}", f"{e}T23:00")
        )

    monkeypatch.setattr(mirror, "fetch_mirror", fake_fetch)
    monkeypatch.setattr(era5_land_mirror, "fetch_mirror", fake_fetch)
    monkeypatch.setattr(
        mirror, "fetch_cds", lambda var, s, e, d, *, client=None: (tmp_path, 1.0)
    )
    cds = era5_land_mirror.daily_totals_from_accumulated(hourly["pev"]).sel(
        valid_time=slice("2000-01-01", "2000-01-31")
    )
    monkeypatch.setattr(mirror, "load_cds", lambda path, var, s, e: cds)
    report = tmp_path / "report.md"

    mirror.main(
        ["--year", "2000", "--months", "1", "--variable", "pev", "--from-cds",
         "--cds-dir", str(tmp_path), "--report", str(report)]
    )

    text = report.read_text()
    assert "accumulated, detected from tp" in text
    assert "| exact match |" in text


def _default_run(monkeypatch, tmp_path, loaded):
    days = pd.date_range("2000-01-01", "2000-01-31", freq="D")
    hours = pd.date_range("1999-12-31T00:00", "2000-01-31T23:00", freq="h")
    hourly = xr.DataArray(
        np.full((hours.size, 1, 1), 0.25),
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": hours, "latitude": [61.0], "longitude": [-150.0]},
    )
    monkeypatch.setattr(mirror, "BASELINE_DATA_ROOT", tmp_path)
    monkeypatch.setenv(mirror.API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(mirror, "open_mirror_store", lambda key: None)
    monkeypatch.setattr(mirror, "fetch_mirror", lambda store, name, s, e: hourly)

    def fake_load(path, var, s, e):
        loaded.append(path)
        return hourly.sel(valid_time=days)

    monkeypatch.setattr(mirror, "load_cds", fake_load)
    report = tmp_path / "report.md"
    mirror.main(
        ["--year", "2000", "--months", "1", "--variable", "swvl1", "--variable",
         "tp", "--accumulation", "accumulated", "--report", str(report)]
    )
    return report.read_text()


def test_default_run_compares_against_the_archived_cds_file(monkeypatch, tmp_path):
    archived = (
        tmp_path
        / "cds_climatology_archive"
        / "era5_land_daily_swvl1_1981_2020"
        / "volumetric_soil_water_level_1_daily_2000.nc"
    )
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"CDS file")
    loaded = []

    text = _default_run(monkeypatch, tmp_path, loaded)

    assert loaded == [archived]
    assert "| swvl1 |" in text


def test_variable_without_an_archived_cds_file_is_skipped_with_the_path(
    monkeypatch, tmp_path
):
    loaded = []

    text = _default_run(monkeypatch, tmp_path, loaded)

    expected = (
        tmp_path
        / "cds_climatology_archive"
        / "era5_land_daily_tp_1981_2020"
        / "total_precipitation_daily_2000.grib"
    )
    assert f"CDS file not found: {expected}" in text


def test_report_no_longer_says_cds_stays_the_source_unless_values_match():
    text = mirror.render_report(period="2000", tested=True, results={})
    assert "only if every value matches exactly" not in text
    assert "keeps downloading from CDS" not in text
    assert "small differences" in text
