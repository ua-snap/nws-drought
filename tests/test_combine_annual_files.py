"""The combine step builds one file from the mirror's yearly netCDF files."""

import sys

import numpy as np
import pandas as pd
import xarray as xr

from baseline_data_generation_scripts import combine_annual_files
from mirror_climatology import CLIMATOLOGY_SUFFIX


def _yearly_tp(path, year):
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    xr.Dataset(
        {"tp": (("valid_time", "latitude", "longitude"), np.full((days.size, 2, 2), year, "float32"))},
        coords={"valid_time": days, "latitude": [72.0, 71.9], "longitude": [-180.0, -179.9]},
    ).to_netcdf(path, engine="h5netcdf")


def test_precipitation_years_combine_in_order_and_grib_files_are_ignored(
    monkeypatch, tmp_path
):
    annual = tmp_path / "era5_land_daily_tp_1981_2020"
    annual.mkdir()
    for year in (2001, 2000):
        _yearly_tp(annual / f"total_precipitation_daily_{year}{CLIMATOLOGY_SUFFIX}", year)
    (annual / "total_precipitation_daily_1999.grib").write_bytes(b"old CDS file")
    combined = tmp_path / "tp_daily_1981_2020_combined.nc"
    monkeypatch.setattr(combine_annual_files, "daily_year_dir_for_var", lambda var: annual)
    monkeypatch.setattr(combine_annual_files, "daily_combined_file_for_var", lambda var: combined)
    monkeypatch.setattr(sys, "argv", ["combine_annual_files", "--var", "tp"])

    assert combine_annual_files.main() == 0

    with xr.open_dataset(combined, engine="h5netcdf") as ds:
        days = pd.DatetimeIndex(ds["valid_time"].values)
        assert days[0] == pd.Timestamp("2000-01-01")
        assert days[-1] == pd.Timestamp("2001-12-31")
        assert days.is_monotonic_increasing and days.size == 366 + 365
        assert ds["tp"].dtype == np.float32
        assert float(ds["tp"].sel(valid_time="2001-06-01").max()) == 2001.0
