"""The combine step builds one file from the mirror's yearly netCDF files, and
only from a complete, mirror-built set of years."""

import sys

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import mirror_climatology
from baseline_data_generation_scripts import combine_annual_files
from mirror_climatology import (
    CLIMATOLOGY_END_YEAR,
    CLIMATOLOGY_START_YEAR,
    CLIMATOLOGY_SUFFIX,
    MIRROR_ATTRS,
)

YEARS = range(CLIMATOLOGY_START_YEAR, CLIMATOLOGY_END_YEAR + 1)


def _yearly_tp(path, year, *, mirror=True):
    dates = pd.DatetimeIndex(mirror_climatology.expected_dates("tp", year))
    ds = xr.Dataset(
        {
            "tp": (
                ("valid_time", "latitude", "longitude"),
                np.full((dates.size, 2, 2), year, "float32"),
            )
        },
        coords={
            "valid_time": dates,
            "latitude": [72.0, 71.9],
            "longitude": [-180.0, -179.9],
        },
    )
    if mirror:
        ds.attrs.update(MIRROR_ATTRS)
    ds.to_netcdf(path, engine="h5netcdf")


@pytest.fixture
def tp_dirs(monkeypatch, tmp_path):
    annual = tmp_path / "era5_land_daily_tp_1981_2020"
    annual.mkdir()
    combined = tmp_path / "tp_daily_1981_2020_combined.nc"
    monkeypatch.setattr(
        combine_annual_files, "daily_year_dir_for_var", lambda var: annual
    )
    monkeypatch.setattr(
        combine_annual_files, "daily_combined_file_for_var", lambda var: combined
    )
    return annual, combined


def _yearly_path(annual, year):
    return annual / f"total_precipitation_daily_{year}{CLIMATOLOGY_SUFFIX}"


def _run(monkeypatch, *extra):
    monkeypatch.setattr(sys, "argv", ["combine_annual_files", "--var", "tp", *extra])
    return combine_annual_files.main()


def test_complete_mirror_years_combine_in_order_and_other_files_are_ignored(
    monkeypatch, tp_dirs
):
    annual, combined = tp_dirs
    for year in reversed(YEARS):
        _yearly_tp(_yearly_path(annual, year), year)
    (annual / "total_precipitation_daily_1999.grib").write_bytes(b"old CDS file")
    # what a download killed mid-write leaves behind
    (annual / "total_precipitation_daily_2002.nc.partial").write_bytes(b"partial")

    assert _run(monkeypatch) == 0

    with xr.open_dataset(combined, engine="h5netcdf") as ds:
        days = pd.DatetimeIndex(ds["valid_time"].values)
        assert days[0] == pd.Timestamp("1981-01-01")
        assert days[-1] == pd.Timestamp("2020-12-31")
        assert days.is_monotonic_increasing
        assert ds["tp"].dtype == np.float32
        assert float(ds["tp"].sel(valid_time="2001-06-01").max()) == 2001.0


def test_missing_year_stops_before_the_existing_combined_file_is_replaced(
    monkeypatch, tp_dirs
):
    annual, combined = tp_dirs
    for year in YEARS:
        if year != 1995:
            _yearly_tp(_yearly_path(annual, year), year)
    combined.write_bytes(b"the previous combined climatology")

    assert _run(monkeypatch, "--overwrite") == 1

    assert combined.read_bytes() == b"the previous combined climatology"


def test_cds_built_year_stops_before_the_existing_combined_file_is_replaced(
    monkeypatch, tp_dirs
):
    annual, combined = tp_dirs
    for year in YEARS:
        _yearly_tp(_yearly_path(annual, year), year, mirror=year != 2010)
    combined.write_bytes(b"the previous combined climatology")

    assert _run(monkeypatch, "--overwrite") == 1

    assert combined.read_bytes() == b"the previous combined climatology"
