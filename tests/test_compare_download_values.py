"""Tests for the old-versus-new download value comparison."""

import numpy as np
import pandas as pd
import xarray as xr

from qc.compare_download_values import compare_arrays, is_identical


def _array(start, days, values=None):
    times = pd.date_range(start, periods=days)
    data = np.arange(days * 2, dtype="float32").reshape(days, 2)
    if values is not None:
        data = values
    return xr.DataArray(data, dims=("valid_time", "x"), coords={"valid_time": times})


def test_identical_downloads_pass():
    old = _array("2026-01-01", 5)
    result = compare_arrays(old, old.copy())
    assert result["differing_values"] == 0
    assert is_identical(result)


def test_one_changed_value_fails():
    old = _array("2026-01-01", 5)
    new = old.copy()
    new[2, 1] = 99.0
    result = compare_arrays(old, new)
    assert result["differing_values"] == 1
    assert not is_identical(result)


def test_missing_value_in_only_one_download_fails():
    old = _array("2026-01-01", 5)
    new = old.copy()
    new[0, 0] = np.nan
    result = compare_arrays(old, new)
    assert result["missing_value_mismatches"] == 1
    assert not is_identical(result)


def test_a_date_only_one_download_holds_fails():
    old = _array("2026-01-01", 5)
    new = old.isel(valid_time=slice(0, 4))
    result = compare_arrays(old, new)
    assert result["dates_only_in_old"] == 1
    assert result["differing_values"] == 0
    assert not is_identical(result)
