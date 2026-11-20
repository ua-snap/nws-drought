"""Tests for the shared Earth Data Hub mirror code: daily rebuilds, the summed-
variable form, the bounding-box cut and the download concurrency cap. Synthetic
arrays only; nothing here touches the network."""

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import era5_land_mirror as mirror


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


@pytest.mark.parametrize("stored", [179.99998, 180.0, 180.00002, -180.0])
def test_dateline_column_wraps_to_minus_180_however_it_is_stored(monkeypatch, stored):
    # The Earth Data Hub store runs 0..359.9; its 180 column must line up with
    # the CDS -180 column whatever float the store keeps for it.
    monkeypatch.setattr(mirror, "DL_BBOX", [72, -180, 51, -129])
    lon = np.round(np.arange(0, 360, 0.1), 1)
    lon[1800] = stored

    _, lon_idx = mirror.bbox_indices(np.array([60.0]), lon)

    assert lon_idx.size == 511
    assert mirror.wrap_longitudes([stored])[0] == -180.0


def test_fetch_downloads_at_most_the_fixed_number_of_blocks_at_once(monkeypatch):
    import dask.array as dsa
    import dask.base

    seen = []
    threaded = dask.base.named_schedulers["threads"]

    def recording_get(dsk, keys, **kwargs):
        seen.append(kwargs.get("num_workers"))
        return threaded(dsk, keys, **kwargs)

    monkeypatch.setitem(dask.base.named_schedulers, "threads", recording_get)
    monkeypatch.setitem(dask.base.named_schedulers, "threading", recording_get)
    hours = pd.date_range("1999-12-31T00:00", "2000-01-02T23:00", freq="h")
    lat = np.array([72.0, 60.0, 51.0])
    lon = np.array([180.0, 200.0, 231.0])
    data = dsa.zeros((hours.size, lat.size, lon.size), chunks=(24, 1, 1))
    store = xr.Dataset(
        {"tp": (("valid_time", "latitude", "longitude"), data)},
        coords={"valid_time": hours, "latitude": lat, "longitude": lon},
    )

    hourly = mirror.fetch_mirror(
        store,
        "tp",
        pd.Timestamp("2000-01-01").date(),
        pd.Timestamp("2000-01-02").date(),
    )

    assert hourly.sizes["valid_time"] == 72
    assert seen == [mirror.MAX_CONCURRENT_FETCHES] == [4]


def test_module_imports_without_the_mirror_packages():
    code = (
        "import sys; sys.modules['zarr'] = None; sys.modules['aiohttp'] = None; "
        "import era5_land_mirror"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
