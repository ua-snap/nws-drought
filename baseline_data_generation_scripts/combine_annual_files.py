#!/usr/bin/env python3
"""Combine annual files with daily data frequency for one variable into one NetCDF."""

import argparse
import logging
import sys
from pathlib import Path

import xarray as xr

from config import daily_combined_file_for_var, daily_year_dir_for_var
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, discover_year_files, setup_logging


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--var",
        type=str,
        required=True,
        choices=sorted(VARIABLE_REGISTRY.keys()),
        help="Variable name for which to combine the files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    return parser.parse_args()


def combine_annual_files(
    annual_paths: list[Path],
    output_file: Path,
    *,
    variable_key: str,
    overwrite: bool,
) -> Path:
    """Combine annual files into one continuous NetCDF."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if output_file.exists():
        if not overwrite:
            logging.info("Skipping existing combined file: %s", output_file)
            return output_file
        output_file.unlink()

    ds: xr.Dataset | None = None

    try:
        if VARIABLE_REGISTRY[variable_key]["suffix"] == ".grib":
            ds = xr.open_mfdataset(
                annual_paths,
                engine="cfgrib",
                data_vars="minimal",
                coords="minimal",
                compat="override",
                backend_kwargs={
                    "time_dims": ["valid_time"],
                    "coords_as_attributes": ["surface", "number"],
                    "indexpath": "",  # grib can spew auxillary .idx files, this halts that behavior
                },
            )
        else:
            ds = xr.open_mfdataset(
                annual_paths,
                combine="by_coords",
                engine=NETCDF_ENGINE,
                data_vars="minimal",
                coords="minimal",
                compat="override",
            ).sortby("valid_time")

        ds.to_netcdf(
            output_file,
            engine=NETCDF_ENGINE,
            encoding={
                VARIABLE_REGISTRY[variable_key]["short_name"]: {"dtype": "float32"}
            },
        )
    finally:
        if ds is not None:
            ds.close()

    logging.info("Wrote combined file: %s", output_file)
    return output_file


def main() -> int:
    """Combine annual files."""
    args = parse_args()

    setup_logging()

    annual_dir = daily_year_dir_for_var(args.var)
    output_file = daily_combined_file_for_var(args.var)
    logging.info("Resolved annual directory: %s", annual_dir)
    logging.info("Resolved combined output file: %s", output_file)

    available_years = discover_year_files(
        annual_dir, args.var, VARIABLE_REGISTRY[args.var]["suffix"]
    )

    annual_paths = list(available_years.values())

    logging.info(
        "Combining %d annual files spanning %s to %s",
        len(annual_paths),
        list(available_years.keys())[0],
        list(available_years.keys())[-1],
    )

    combine_annual_files(
        annual_paths=annual_paths,
        output_file=output_file,
        variable_key=args.var,
        overwrite=args.overwrite,
    )

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
