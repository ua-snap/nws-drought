"""Tests for the climatology download from the Earth Data Hub mirror. The store is
an in-memory dataset laid out like the real one (0..360 longitudes, the dateline
column stored just below 180, latitudes north to south with 72 stored a hair
high); nothing here touches the network."""

import datetime
import logging

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import era5_land_mirror
import mirror_climatology
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import check_output_file

KEY = "secret-test-key-value"
STORE_LAT = np.array([73.0, 72.0000001, 60.0, 51.0, 50.0])
STORE_LON = np.array([10.0, 179.99998, 200.0, 231.0, 232.0])


def _tp_hourly(hours: pd.DatetimeIndex, *, increments: bool) -> np.ndarray:
    """Hour k (1 = 01:00 ... 24 = 00:00 next day) of accumulation day D adds
    doy(D) * 1e-5 * 0.5 for odd k and * 1.5 for even k, so the day's 24 hours add
    up to 24 * doy(D) * 1e-5. Running totals since 00 UTC are returned unless
    ``increments``."""
    day = (hours - pd.Timedelta(hours=1)).floor("D")
    scale = day.dayofyear.values * 1e-5
    k = (hours.hour.values - 1) % 24 + 1
    if increments:
        return scale * np.where(k % 2, 0.5, 1.5)
    return scale * (k - (k % 2) * 0.5)


def _swvl1_values(hours: pd.DatetimeIndex) -> np.ndarray:
    """doy + hour / 100, so the 00/06/12/18 mean on day D is doy(D) + 0.09."""
    return hours.dayofyear.values + hours.hour.values / 100.0


def make_store(first: str, last: str, *, increments: bool = False) -> xr.Dataset:
    hours = pd.date_range(f"{first}T00:00", f"{last}T23:00", freq="h")
    shape = (hours.size, STORE_LAT.size, STORE_LON.size)
    tp = _tp_hourly(hours, increments=increments)
    fields = {
        "tp": np.broadcast_to(tp[:, None, None], shape).astype("float32"),
        "pev": np.broadcast_to(-tp[:, None, None], shape).astype("float32"),
        "swvl1": np.broadcast_to(_swvl1_values(hours)[:, None, None], shape).astype(
            "float32"
        ),
    }
    store = xr.Dataset(
        {
            name: (("valid_time", "latitude", "longitude"), values.copy())
            for name, values in fields.items()
        },
        coords={"valid_time": hours, "latitude": STORE_LAT, "longitude": STORE_LON},
    )
    for name in store.data_vars:
        store[name].attrs = {"units": "m", "long_name": f"{name} from the store"}
    return store


@pytest.fixture
def baseline_root(monkeypatch, tmp_path):
    root = tmp_path / "baseline"
    monkeypatch.setattr(mirror_climatology, "BASELINE_DATA_ROOT", root)
    monkeypatch.setattr(era5_land_mirror, "DL_BBOX", [72, -180, 51, -129])
    monkeypatch.setenv(era5_land_mirror.API_KEY_ENV_VAR, KEY)
    return root


@pytest.fixture
def use_store(monkeypatch):
    """Serve ``store`` in place of the real mirror and count the fetches."""
    fetched = []
    real_fetch = era5_land_mirror.fetch_mirror

    def install(store):
        monkeypatch.setattr(era5_land_mirror, "open_mirror_store", lambda key: store)

        def counting_fetch(s, name, start, end):
            fetched.append((name, start, end))
            return real_fetch(s, name, start, end)

        monkeypatch.setattr(era5_land_mirror, "fetch_mirror", counting_fetch)
        return fetched

    return install


def run(variables, start, end):
    mirror_climatology.download_era5_land_climatology(
        variables, start_year=start, end_year=end
    )


def yearly(var, year):
    return mirror_climatology.climatology_file_path(var, year)


def test_precipitation_year_labels_each_total_by_the_day_it_measures(
    baseline_root, use_store
):
    use_store(make_store("1999-12-30", "2001-01-01"))

    run(["tp"], 2000, 2000)

    path = yearly("tp", 2000)
    assert path.name == "total_precipitation_daily_2000.nc"
    assert path.parent.name == "era5_land_daily_tp_1981_2020"
    with xr.open_dataset(path, engine="h5netcdf") as ds:
        days = pd.DatetimeIndex(ds["valid_time"].values)
        assert days[0] == pd.Timestamp("2000-01-01") and days.size == 366
        # every hour of accumulation day D adds doy(D) * 1e-5, so the day's total
        # is 24 * doy(D) * 1e-5: 1 Mar 2000 is day 61
        np.testing.assert_allclose(
            ds["tp"].sel(valid_time="2000-03-01").values, 24 * 61 * 1e-5, rtol=1e-6
        )
        np.testing.assert_allclose(
            ds["tp"].sel(valid_time="2000-01-01").values, 24 * 1 * 1e-5, rtol=1e-6
        )
        # 31 Dec 2000, read from the store's 00:00 value on 1 Jan 2001
        np.testing.assert_allclose(
            ds["tp"].sel(valid_time="2000-12-31").values, 24 * 366 * 1e-5, rtol=1e-6
        )
        assert ds["tp"].dtype == np.float32
        assert ds["tp"].attrs["units"] == "m"
        assert era5_land_mirror.EDH_STORE_URL in ds.attrs["source"]
    assert check_output_file(path, "tp", mirror_climatology.expected_dates("tp", 2000))[
        0
    ]


def test_hourly_increments_give_the_same_year_as_running_totals(
    baseline_root, use_store, tmp_path
):
    use_store(make_store("1999-12-30", "2001-01-01"))
    run(["tp"], 2000, 2000)
    with xr.open_dataset(yearly("tp", 2000), engine="h5netcdf") as ds:
        from_totals = ds["tp"].load()
    yearly("tp", 2000).unlink()

    use_store(make_store("1999-12-30", "2001-01-01", increments=True))
    run(["tp"], 2000, 2000)

    with xr.open_dataset(yearly("tp", 2000), engine="h5netcdf") as ds:
        xr.testing.assert_allclose(ds["tp"].load(), from_totals, rtol=1e-5)


def test_soil_moisture_day_is_the_mean_of_the_four_six_hourly_values(
    baseline_root, use_store
):
    use_store(make_store("1999-12-31", "2000-12-31"))

    run(["swvl1"], 2000, 2000)

    with xr.open_dataset(yearly("swvl1", 2000), engine="h5netcdf") as ds:
        assert ds.sizes["valid_time"] == 366
        # 1 Mar 2000 is day 61; the mean of all 24 hours would add 0.115, not 0.09
        np.testing.assert_allclose(
            ds["swvl1"].sel(valid_time="2000-03-01").values, 61.09, rtol=1e-6
        )


def test_climatology_ends_with_2020_for_every_variable(baseline_root, use_store):
    use_store(make_store("2019-12-30", "2021-01-01"))

    run(["tp", "swvl1"], 2020, mirror_climatology.CLIMATOLOGY_END_YEAR)

    assert mirror_climatology.CLIMATOLOGY_END_YEAR == 2020
    for var in ("tp", "swvl1"):
        with xr.open_dataset(yearly(var, 2020), engine="h5netcdf") as ds:
            days = pd.DatetimeIndex(ds["valid_time"].values)
            assert days[0] == pd.Timestamp("2020-01-01")
            assert days[-1] == pd.Timestamp("2020-12-31") and days.size == 366
        assert not yearly(var, 2021).exists()


def test_grid_matches_the_cds_box_and_order(baseline_root, use_store):
    use_store(make_store("1999-12-31", "2000-12-31"))

    run(["swvl1"], 2000, 2000)

    with xr.open_dataset(yearly("swvl1", 2000), engine="h5netcdf") as ds:
        # 72 stored a hair high and the dateline column stored just below 180 are
        # kept; 73 and 50 N and the columns outside the box are dropped
        assert np.round(ds["latitude"].values, 4).tolist() == [72.0, 60.0, 51.0]
        assert np.round(ds["longitude"].values, 4).tolist() == [-180.0, -160.0, -129.0]
        assert ds["swvl1"].dims == ("valid_time", "latitude", "longitude")


def test_rerun_fetches_only_years_without_a_finished_mirror_file(
    baseline_root, use_store
):
    fetched = use_store(make_store("1999-12-31", "2002-12-31"))
    run(["swvl1"], 2000, 2000)
    # a stopped run's staged file next to 2001
    staged = mirror_climatology.staged_path(yearly("swvl1", 2001))
    staged.write_bytes(b"partial")
    fetched.clear()

    run(["swvl1"], 2000, 2002)

    assert [(name, start.year) for name, start, _ in fetched] == [
        ("swvl1", 2001),
        ("swvl1", 2002),
    ]
    assert not staged.exists()
    for year in (2000, 2001, 2002):
        assert mirror_climatology.is_mirror_built("swvl1", year)


def test_mirror_file_missing_a_day_is_fetched_again(baseline_root, use_store):
    fetched = use_store(make_store("1999-12-31", "2000-12-31"))
    run(["swvl1"], 2000, 2000)
    path = yearly("swvl1", 2000)
    with xr.open_dataset(path, engine="h5netcdf") as ds:
        short = ds.isel(valid_time=slice(1, None)).load()
    short.to_netcdf(path, engine="h5netcdf")
    fetched.clear()

    run(["swvl1"], 2000, 2000)

    assert len(fetched) == 1
    assert mirror_climatology.is_mirror_built("swvl1", 2000)


def test_missing_key_stops_before_opening_the_store_or_writing_files(
    baseline_root, use_store, monkeypatch
):
    monkeypatch.delenv(era5_land_mirror.API_KEY_ENV_VAR)

    def no_open(key):
        raise AssertionError("the store must not be opened without a key")

    monkeypatch.setattr(era5_land_mirror, "open_mirror_store", no_open)

    with pytest.raises(mirror_climatology.MirrorKeyMissing, match="EDH_API_KEY"):
        run(["swvl1"], 2000, 2000)

    assert not yearly("swvl1", 2000).exists()


def test_rejected_key_says_so_and_differs_from_a_missing_key(
    baseline_root, monkeypatch
):
    class Refused(Exception):
        status = 401

    def refuse(key):
        raise Refused("401 Unauthorized")

    monkeypatch.setattr(era5_land_mirror, "open_mirror_store", refuse)

    with pytest.raises(mirror_climatology.MirrorUnavailable, match="rejected") as err:
        run(["swvl1"], 2000, 2000)

    assert KEY not in str(err.value)
    assert not yearly("swvl1", 2000).exists()


def test_fetch_error_keeps_finished_years_and_leaves_no_partial_file(
    baseline_root, use_store, monkeypatch
):
    use_store(make_store("1999-12-31", "2001-12-31"))
    real_fetch = era5_land_mirror.fetch_mirror

    def failing_in_2001(store, name, start, end):
        if start.year == 2001:
            raise OSError("connection reset")
        return real_fetch(store, name, start, end)

    monkeypatch.setattr(era5_land_mirror, "fetch_mirror", failing_in_2001)

    with pytest.raises(OSError, match="connection reset"):
        run(["swvl1"], 2000, 2001)

    assert mirror_climatology.is_mirror_built("swvl1", 2000)
    assert not yearly("swvl1", 2001).exists()
    assert not mirror_climatology.staged_path(yearly("swvl1", 2001)).exists()


def test_log_names_each_year_and_the_total_and_never_the_key(
    baseline_root, use_store, caplog
):
    use_store(make_store("1999-12-31", "2001-12-31"))

    with caplog.at_level(logging.INFO, logger="mirror_climatology"):
        run(["swvl1"], 2000, 2001)

    text = caplog.text
    assert "swvl1 2000" in text and "swvl1 2001" in text
    assert "Climatology download finished" in text
    assert f"{era5_land_mirror.MAX_CONCURRENT_FETCHES} storage blocks" in text
    assert KEY not in text


def test_summed_form_is_read_from_precipitation_even_when_only_evaporation_runs(
    baseline_root, use_store, monkeypatch
):
    use_store(make_store("1999-12-30", "2001-01-01"))
    asked = []
    real = era5_land_mirror.store_accumulation_convention

    def recording(store, start):
        asked.append(start)
        return real(store, start)

    monkeypatch.setattr(era5_land_mirror, "store_accumulation_convention", recording)

    run(["pev"], 2000, 2000)

    assert asked == [datetime.date(2000, 1, 1)]
    assert mirror_climatology.is_mirror_built("pev", 2000)


def test_grid_coordinates_are_the_cds_floats_so_files_align_exactly(
    baseline_root, use_store
):
    # CDS stores coordinates such as 71.80000000000001; the indices divide
    # recent CDS data by the climatology, which needs identical coordinates
    use_store(make_store("1999-12-31", "2000-12-31"))
    grid = mirror_climatology.cds_grid()
    cds_lat = [v for v in grid["latitude"] if round(v, 4) in (72.0, 60.0, 51.0)]
    cds_lon = [v for v in grid["longitude"] if round(v, 4) in (-180.0, -160.0, -129.0)]

    run(["swvl1"], 2000, 2000)

    with xr.open_dataset(yearly("swvl1", 2000), engine="h5netcdf") as ds:
        assert ds["latitude"].values.tolist() == cds_lat
        assert ds["longitude"].values.tolist() == cds_lon
        recent = xr.DataArray(
            np.ones((3, 3)),
            dims=("latitude", "longitude"),
            coords={"latitude": cds_lat, "longitude": cds_lon},
        )
        xr.align(ds["swvl1"].isel(valid_time=0), recent, join="exact")


def test_pinned_grid_holds_the_whole_cds_box():
    grid = mirror_climatology.cds_grid()
    assert len(grid["latitude"]) == 211 and len(grid["longitude"]) == 511
    assert grid["latitude"][2] == 71.80000000000001
    assert round(grid["longitude"][0], 4) == -180.0
    assert round(grid["longitude"][-1], 4) == -129.0


def test_mirror_point_off_the_cds_grid_stops_the_year(baseline_root, use_store):
    store = make_store("1999-12-31", "2000-12-31")
    use_store(store.assign_coords(latitude=STORE_LAT + np.array([0, 0, 0.03, 0, 0])))

    with pytest.raises(RuntimeError, match="CDS grid"):
        run(["swvl1"], 2000, 2000)

    assert not yearly("swvl1", 2000).exists()


def test_staged_file_is_never_found_as_a_yearly_file(baseline_root, use_store):
    from file_helpers import discover_year_files

    use_store(make_store("1999-12-31", "2000-12-31"))
    run(["swvl1"], 2000, 2000)
    staged = mirror_climatology.staged_path(yearly("swvl1", 2001))
    staged.write_bytes(b"left by a killed run")

    found = discover_year_files(
        yearly("swvl1", 2000).parent, "swvl1", mirror_climatology.CLIMATOLOGY_SUFFIX
    )

    assert list(found) == [2000]
