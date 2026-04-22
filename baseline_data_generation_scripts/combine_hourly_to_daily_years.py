#!/usr/bin/env python3
"""Combine annual UTC-9 daily files for one variable into one NetCDF.

Expected annual filenames:
    <var>_daily_utc_minus9_YYYY.nc

Examples
--------
python combine_hourly_to_daily_years.py \
    --annual-dir /path/to/annual_nc \
    --output-file /path/to/out/tp_daily_utc_minus9_combined.nc \
    --var tp

python combine_hourly_to_daily_years.py \
    --annual-dir /path/to/annual_nc \
    --output-file /path/to/out/pev_daily_utc_minus9_combined.nc \
    --var pev

python combine_hourly_to_daily_years.py \
    --annual-dir /path/to/annual_nc \
    --output-file /path/to/out/swvl1_daily_utc_minus9_combined.nc \
    --var swvl1
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import xarray as xr

NETCDF_ENGINE = "h5netcdf"
SUPPORTED_VARS = {"tp", "pev", "swe", "swvl1", "swvl2"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--annual-dir",
        type=Path,
        required=True,
        help="Directory containing annual NetCDF files.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Combined NetCDF output file path.",
    )
    parser.add_argument(
        "--var",
        type=str,
        required=True,
        choices=sorted(SUPPORTED_VARS),
        help="Variable name for annual filenames and NetCDF variable encoding.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _year_from_annual_filename(path: Path, *, varname: str) -> int:
    """Parse year from expected annual filename format."""
    match = re.fullmatch(
        rf"{re.escape(varname)}_daily_utc_minus9_(\d{{4}})\.nc", path.name
    )
    if not match:
        raise ValueError(
            f"Expected annual filename like {varname}_daily_utc_minus9_1982.nc, got "
            f"{path.name!r}"
        )
    return int(match.group(1))


def discover_annual_files(annual_dir: Path, *, varname: str) -> dict[int, Path]:
    """Discover annual files keyed by year."""
    if not annual_dir.exists():
        raise FileNotFoundError(f"Annual directory does not exist: {annual_dir}")
    if not annual_dir.is_dir():
        raise NotADirectoryError(f"Annual path is not a directory: {annual_dir}")

    annual_pattern = f"{varname}_daily_utc_minus9_*.nc"
    paths = sorted(p for p in annual_dir.glob(annual_pattern) if p.is_file())
    if not paths:
        raise FileNotFoundError(
            f"No files matching {annual_pattern!r} found in {annual_dir}"
        )

    year_to_path: dict[int, Path] = {}
    for path in paths:
        try:
            year = _year_from_annual_filename(path, varname=varname)
        except ValueError:
            logging.info("Skipping non-annual file: %s", path.name)
            continue
        if year in year_to_path:
            raise ValueError(
                f"Multiple annual files mapped to {year}: "
                f"{year_to_path[year].name}, {path.name}"
            )
        year_to_path[year] = path

    if not year_to_path:
        raise FileNotFoundError(
            f"No annual files named like {varname}_daily_utc_minus9_YYYY.nc found in "
            f"{annual_dir}"
        )

    return dict(sorted(year_to_path.items()))


def combine_annual_files(
    annual_paths: list[Path],
    output_file: Path,
    *,
    varname: str,
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
        ds = xr.open_mfdataset(
            annual_paths,
            combine="by_coords",
            engine=NETCDF_ENGINE,
            data_vars="minimal",
            coords="minimal",
            compat="override",
        ).sortby("time")

        ds.to_netcdf(
            output_file,
            engine=NETCDF_ENGINE,
            encoding={varname: {"dtype": "float32"}},
        )
    finally:
        if ds is not None:
            ds.close()

    logging.info("Wrote combined file: %s", output_file)
    return output_file


def main() -> int:
    """Run annual combination workflow."""
    args = parse_args()
    setup_logging()

    year_to_path = discover_annual_files(args.annual_dir, varname=args.var)
    available_years = sorted(year_to_path)
    logging.info(
        "Discovered %d annual files spanning %s to %s",
        len(available_years),
        available_years[0],
        available_years[-1],
    )

    annual_paths = [year_to_path[y] for y in available_years]

    logging.info(
        "Combining %d annual files spanning %s to %s",
        len(annual_paths),
        available_years[0],
        available_years[-1],
    )
    combine_annual_files(
        annual_paths=annual_paths,
        output_file=args.output_file,
        varname=args.var,
        overwrite=args.overwrite,
    )
    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
