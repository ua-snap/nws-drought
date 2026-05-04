#!/usr/bin/env python3
"""Construct a DOY climatology from a daily NetCDF file."""

import argparse
import logging
import sys

import xarray as xr

from config import climo_file_for_var, daily_combined_file_for_var
from era5_land_variable_registry import SUPPORTED_VARS, VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, setup_logging


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--var",
        type=str,
        required=True,
        choices=SUPPORTED_VARS,
        help="Variable name for which to construct the climatology.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    return parser.parse_args()


def construct_climatology(
    variable_key: str,
    ds: xr.Dataset,
) -> xr.DataArray:
    """Return day-of-year climatology."""
    da = ds[VARIABLE_REGISTRY[variable_key]["short_name"]]
    da.name = VARIABLE_REGISTRY[variable_key]["short_name"]
    clim = da.groupby("valid_time.dayofyear").mean(dim="valid_time")
    clim = clim.rename({"dayofyear": "time"})
    clim.name = da.name
    clim.attrs.setdefault(
        "long_name",
        VARIABLE_REGISTRY[variable_key]["long_name"],
    )
    clim["time"].attrs.setdefault("long_name", "day of year")
    clim["time"].attrs.setdefault("description", "calendar day of year (1-366)")
    return clim


def main() -> int:
    """Run the climatology construction."""
    args = parse_args()
    variable_key = args.var

    setup_logging()

    combined_file = daily_combined_file_for_var(variable_key)
    out_path = climo_file_for_var(variable_key)
    logging.info(f"Resolved input file: {combined_file}")
    logging.info(f"Resolved output file: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logging.info(f"Output already exists: {out_path}")
        return 0

    ds: xr.Dataset | None = (
        None  # initialize so the finally block can safely close ds only if it was opened
    )
    try:
        if not combined_file.is_file():
            raise FileNotFoundError(f"Combined file not found: {combined_file}")

        ds = xr.open_dataset(combined_file, engine=NETCDF_ENGINE)
        if VARIABLE_REGISTRY[variable_key]["short_name"] not in ds.data_vars:
            raise ValueError(
                f"Did not find expected data variable in {combined_file}, "
                f"found {list(ds.data_vars)}"
            )

        clim_da = construct_climatology(variable_key, ds)
        out_ds = clim_da.to_dataset()

        out_ds.to_netcdf(
            out_path,
            engine=NETCDF_ENGINE,
            encoding={
                VARIABLE_REGISTRY[variable_key]["short_name"]: {"dtype": "float32"}
            },
        )
        logging.info(f"Wrote {out_path}")
    finally:
        if ds is not None:
            ds.close()

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
