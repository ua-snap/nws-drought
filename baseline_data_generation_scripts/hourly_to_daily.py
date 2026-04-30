#!/usr/bin/env python3
"""Build UTC-9 daily annual NetCDF files from hourly ERA5-Land GRIB.

This script expects a flat directory of yearly GRIB files, one per year.
Daily aggregation logic lives in ``nws_drought.era5_land.utc9`` (shared with the
operational pipeline).

Examples
--------
python hourly_to_daily.py \\
    --var tp \\
    --year 1982

python hourly_to_daily.py \\
    --var pev
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from nws_drought.era5_land.registry import SUPPORTED_VARS
from nws_drought.era5_land.utc9 import (
    BOUNDARY_PADDING_YEAR,
    compute_one_year,
    discover_year_files,
)

NETCDF_ENGINE = "h5netcdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--var",
        type=str,
        required=True,
        choices=sorted(SUPPORTED_VARS),
        help="Variable registry key (tp, pev, swe, swvl1, swvl2).",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "Optional single year to process. If omitted, all discovered years are "
            "processed."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def write_annual_file(
    ds,
    output_path: Path,
    *,
    varname: str,
    overwrite: bool,
) -> Path:
    if output_path.exists():
        if not overwrite:
            logging.info("Skipping existing annual file: %s", output_path)
            return output_path
        output_path.unlink()

    ds.to_netcdf(
        output_path,
        engine=NETCDF_ENGINE,
        encoding={varname: {"dtype": "float32"}},
    )
    logging.info("Wrote annual file: %s", output_path)
    return output_path


def main() -> int:
    args = parse_args()
    setup_logging()
    from config import daily_year_dir_for_var, hourly_dir_for_var

    input_dir = hourly_dir_for_var(args.var)
    output_dir = daily_year_dir_for_var(args.var)
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Resolved input directory: %s", input_dir)
    logging.info("Resolved output directory: %s", output_dir)

    year_to_path = discover_year_files(input_dir, varname=args.var)
    discovered_years = sorted(year_to_path)

    if not discovered_years:
        raise RuntimeError("No yearly GRIB files were discovered.")

    logging.info(
        "Discovered %d yearly GRIB files spanning %s to %s",
        len(discovered_years),
        discovered_years[0],
        discovered_years[-1],
    )

    if args.year is not None:
        if args.year == BOUNDARY_PADDING_YEAR:
            raise ValueError(
                f"Year {BOUNDARY_PADDING_YEAR} is only used as boundary padding for "
                f"{BOUNDARY_PADDING_YEAR - 1}; no annual NetCDF is produced. "
                f"Use --year {BOUNDARY_PADDING_YEAR - 1} or omit --year."
            )
        if args.year not in year_to_path:
            raise ValueError(
                f"Requested --year {args.year} but no matching input file was found."
            )
        years_to_process = [args.year]
        logging.info("Processing single requested year: %s", args.year)
    else:
        years_to_process = [y for y in discovered_years if y != BOUNDARY_PADDING_YEAR]
        logging.info(
            "Processing all discovered years (excluding boundary-only %s).",
            BOUNDARY_PADDING_YEAR,
        )

    for year in years_to_process:
        current_path = year_to_path[year]
        next_path = year_to_path.get(year + 1)

        ds_year = compute_one_year(
            varname=args.var,
            year=year,
            current_path=current_path,
            next_path=next_path,
        )

        annual_path = output_dir / f"{args.var}_daily_utc_minus9_{year}.nc"
        write_annual_file(
            ds=ds_year,
            output_path=annual_path,
            varname=args.var,
            overwrite=args.overwrite,
        )
        ds_year.close()

        if next_path is None:
            logging.warning(
                "No %s file was found, so the final UTC-9 local day of %s "
                "cannot be computed. Output for that year will end one day early.",
                year + 1,
                year,
            )

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
