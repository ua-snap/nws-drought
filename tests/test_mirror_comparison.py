"""Tests for the cloud-mirror comparison: daily rebuilds, difference statistics, and
the no-API-key path. Synthetic arrays only; nothing here touches the network."""

import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from baseline_data_generation_scripts import compare_era5_land_mirror as mirror


def _hourly(values: np.ndarray, start: str) -> xr.DataArray:
    """Wrap a (time, lat, lon) array as an hourly DataArray on a tiny grid."""
    times = pd.date_range(start, periods=values.shape[0], freq="h")
    return xr.DataArray(
        values,
        dims=("valid_time", "latitude", "longitude"),
        coords={
            "valid_time": times,
            "latitude": [61.0, 60.9],
            "longitude": [-150.0, -149.9],
        },
    )


def _synthetic_increments(n_days: int, seed: int = 0) -> np.ndarray:
    """Hourly increments for hours 01:00 of day 1 through 00:00 of day n_days+1."""
    rng = np.random.default_rng(seed)
    inc = rng.uniform(0.0, 1e-3, size=(24 * n_days, 2, 2))
    inc[rng.uniform(size=inc.shape) < 0.3] = 0.0
    return inc


def _accumulate_from_midnight(increments: np.ndarray) -> np.ndarray:
    """ERA5-Land style: running total since 00 UTC, with 00:00 holding the full prior day."""
    n_days = increments.shape[0] // 24
    days = increments.reshape(n_days, 24, *increments.shape[1:])
    return np.cumsum(days, axis=1).reshape(increments.shape)


def test_accumulated_daily_total_is_next_day_midnight_value():
    increments = _synthetic_increments(3)
    accumulated = _accumulate_from_midnight(increments)
    # first sample is 01:00 on 1 Jan, so 00:00 values land on 2, 3 and 4 Jan
    hourly = _hourly(accumulated, "2000-01-01T01:00")

    daily = mirror.daily_totals_from_accumulated(hourly)

    midnights = hourly.sel(valid_time=hourly.valid_time.dt.hour == 0)
    assert list(daily.valid_time.values) == list(midnights.valid_time.values)
    np.testing.assert_array_equal(daily.values, midnights.values)
    # the 00:00 value is the full 24-hour total for the previous day
    np.testing.assert_allclose(
        daily.values, increments.reshape(3, 24, 2, 2).sum(axis=1)
    )


def test_summed_increments_give_same_daily_totals_as_accumulated_form():
    increments = _synthetic_increments(3, seed=1)
    accumulated = _accumulate_from_midnight(increments)

    from_acc = mirror.daily_totals_from_accumulated(
        _hourly(accumulated, "2000-01-01T01:00")
    )
    from_inc = mirror.daily_totals_from_increments(
        _hourly(increments, "2000-01-01T01:00")
    )

    assert list(from_inc.valid_time.values) == list(from_acc.valid_time.values)
    np.testing.assert_allclose(from_inc.values, from_acc.values, rtol=1e-12)


def test_increment_sum_drops_days_without_all_24_hours():
    increments = _synthetic_increments(2, seed=2)
    # drop 01:00 on 1 Jan, so 1 Jan has only 23 of its 24 increments
    hourly = _hourly(increments[1:], "2000-01-01T02:00")

    daily = mirror.daily_totals_from_increments(hourly)

    assert list(pd.DatetimeIndex(daily.valid_time.values)) == [
        pd.Timestamp("2000-01-03T00:00")
    ]


def test_convention_detection_tells_accumulated_from_increments():
    increments = _synthetic_increments(5, seed=3)
    accumulated = _accumulate_from_midnight(increments)

    assert (
        mirror.detect_accumulation_convention(_hourly(accumulated, "2000-01-01T01:00"))
        == "accumulated"
    )
    assert (
        mirror.detect_accumulation_convention(_hourly(increments, "2000-01-01T01:00"))
        == "increments"
    )


def test_daily_mean_uses_only_00_06_12_18_utc():
    hours = np.arange(48, dtype=float)
    values = np.broadcast_to(hours[:, None, None], (48, 2, 2)).copy()
    hourly = _hourly(values, "2000-01-01T00:00")

    daily = mirror.daily_mean_6_hourly(hourly)

    # day 1: mean(0, 6, 12, 18) = 9; mean of all 24 hours would be 11.5
    assert list(pd.DatetimeIndex(daily.valid_time.values)) == [
        pd.Timestamp("2000-01-01"),
        pd.Timestamp("2000-01-02"),
    ]
    np.testing.assert_array_equal(daily.isel(valid_time=0).values, 9.0)
    np.testing.assert_array_equal(daily.isel(valid_time=1).values, 33.0)


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


def test_box_edges_stored_slightly_outside_are_kept(monkeypatch):
    monkeypatch.setattr(mirror, "DL_BBOX", [72, -180, 51, -129])
    # descending latitudes with 72 stored as 72.0000001; longitudes 0..360
    lat = np.round(np.arange(90, -90.05, -0.1), 1)
    lat[lat == 72.0] = 72.0000001
    lon = np.round(np.arange(0, 360, 0.1), 1)

    lat_idx, lon_idx = mirror.bbox_indices(lat, lon)

    assert lat_idx.size == 211
    assert lat[lat_idx].max() == pytest.approx(72.0)
    assert lon_idx.size == 511
    picked = ((lon[lon_idx] + 180) % 360) - 180
    assert picked.min() == pytest.approx(-180.0)
    assert picked.max() == pytest.approx(-129.0)


def test_box_on_a_grid_holding_plus_180_keeps_the_dateline_column(monkeypatch):
    monkeypatch.setattr(mirror, "DL_BBOX", [72, -180, 51, -129])
    lon = np.round(np.arange(-179.9, 180.05, 0.1), 1)  # +180 present, -180 absent

    _, lon_idx = mirror.bbox_indices(np.array([60.0]), lon)

    assert lon_idx.size == 511
    assert 180.0 in lon[lon_idx]


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


@pytest.mark.parametrize("stored", [179.99998, 180.0, 180.00002, -180.0])
def test_dateline_column_wraps_to_minus_180_however_it_is_stored(
    monkeypatch, stored
):
    # The Earth Data Hub store runs 0..359.9; its 180 column must line up with
    # the CDS -180 column whatever float the store keeps for it.
    monkeypatch.setattr(mirror, "DL_BBOX", [72, -180, 51, -129])
    lon = np.round(np.arange(0, 360, 0.1), 1)
    lon[1800] = stored

    _, lon_idx = mirror.bbox_indices(np.array([60.0]), lon)

    assert lon_idx.size == 511
    assert mirror.wrap_longitudes([stored])[0] == -180.0
