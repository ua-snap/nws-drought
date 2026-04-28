"""Download hourly ERA5-Land data (1981–2020) for climatology workflows."""

import argparse
import logging

import cdsapi

from config import DL_BBOX, api_credentials_check, hourly_dir_for_var

from download_scripts.era5_land_variable_registry import (
    VARIABLE_REGISTRY,
)

_HOURLY_TIMES = [f"{hour:02d}:00" for hour in range(24)]


def _build_year_request(cds_variable: str, year: int) -> dict:
    return {
        "variable": cds_variable,
        "year": str(year),
        "month": [str(month).zfill(2) for month in range(1, 13)],
        "day": [str(day).zfill(2) for day in range(1, 32)],
        "time": list(_HOURLY_TIMES),
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def download_era5_land_climatology(
    variable_key: str,
    start_year: int = 1981,
    end_year: int = 2020,
) -> None:
    """Download ERA5-Land hourly fields for one variable over [start_year, end_year]."""
    meta = VARIABLE_REGISTRY[variable_key]
    cds_variable = meta["cds_variable"]
    hourly_prefix = meta["hourly_prefix"]
    download_dir = hourly_dir_for_var(variable_key)
    download_dir.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()

    for year in range(start_year, end_year + 1):
        logging.info(
            "Downloading %s (%s) for %s to %s",
            variable_key,
            cds_variable,
            year,
            download_dir,
        )
        request = _build_year_request(cds_variable, year)
        dst = download_dir / f"{hourly_prefix}{year}.grib"
        client.retrieve("reanalysis-era5-land", request, target=dst)


def main() -> None:
    choices = sorted(VARIABLE_REGISTRY.keys())
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Example: python -m download_scripts.download_era5_land_climo -v tp"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--variable",
        dest="variable",
        type=str,
        required=True,
        choices=choices,
        metavar="VAR",
        help=f"Variable key: {', '.join(choices)}",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1981,
        help="First calendar year to retrieve (inclusive).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2020,
        help="Last calendar year to retrieve (inclusive).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    api_credentials_check()
    download_era5_land_climatology(
        args.variable,
        start_year=args.start_year,
        end_year=args.end_year,
    )


if __name__ == "__main__":
    main()
