"""Tests for the output file check (variable and dates held by a downloaded file)."""

import numpy as np
import pandas as pd
import xarray as xr

import file_helpers
from file_helpers import check_output_file


def _write_nc(path, var, dates):
    times = pd.DatetimeIndex(dates)
    ds = xr.Dataset(
        {var: (("valid_time", "latitude"), np.ones((len(times), 2)))},
        coords={"valid_time": times, "latitude": [60.0, 61.0]},
    )
    ds.to_netcdf(path, engine=file_helpers.NETCDF_ENGINE)


MARCH = list(pd.date_range("2020-03-01", "2020-03-31", freq="D"))
APRIL = list(pd.date_range("2020-04-01", "2020-04-30", freq="D"))


def test_matching_variable_and_dates_pass(tmp_path):
    fp = tmp_path / "swvl1.nc"
    _write_nc(fp, "swvl1", MARCH)
    ok, reason = check_output_file(fp, "swvl1", MARCH)
    assert ok, reason


def test_wrong_dates_fail_with_reason(tmp_path):
    fp = tmp_path / "swvl1.nc"
    _write_nc(fp, "swvl1", MARCH)
    ok, reason = check_output_file(fp, "swvl1", APRIL)
    assert not ok
    assert "dates" in reason


def test_wrong_variable_fails_with_reason(tmp_path):
    fp = tmp_path / "swvl1.nc"
    _write_nc(fp, "swvl1", MARCH)
    ok, reason = check_output_file(fp, "swvl2", MARCH)
    assert not ok
    assert "swvl2" in reason


def test_missing_last_day_fails(tmp_path):
    fp = tmp_path / "swvl1.nc"
    _write_nc(fp, "swvl1", MARCH[:-1])
    ok, reason = check_output_file(fp, "swvl1", MARCH)
    assert not ok
    assert "2020-03-31" in reason


def test_unreadable_file_fails_without_raising(tmp_path):
    fp = tmp_path / "swvl1.nc"
    fp.write_bytes(b"not a netcdf file")
    ok, reason = check_output_file(fp, "swvl1", MARCH)
    assert not ok
    assert "could not be opened" in reason


def test_grib_midnight_valid_times_pass(tmp_path, monkeypatch):
    fp = tmp_path / "tp.grib"
    fp.write_bytes(b"")
    stub = xr.Dataset(
        {"tp": (("valid_time",), np.ones(len(MARCH)))},
        coords={"valid_time": pd.DatetimeIndex(MARCH)},
    )
    seen = {}

    def fake_open_dataset(path, **kwargs):
        seen.update(kwargs)
        return stub

    monkeypatch.setattr(file_helpers.xr, "open_dataset", fake_open_dataset)
    ok, reason = check_output_file(fp, "tp", MARCH)
    assert ok, reason
    assert seen["engine"] == "cfgrib"
    assert seen["backend_kwargs"] == file_helpers.GRIB_BACKEND_KWARGS
