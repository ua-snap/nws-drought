"""Download the ERA5-Land (1981–2020) climatology."""

import argparse
import logging

from download_helpers import api_credentials_check, download_era5_land_climatology
from era5_land_variable_registry import VARIABLE_REGISTRY


def main() -> None:
    api_credentials_check()
    choices = sorted(VARIABLE_REGISTRY.keys())
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Example: python download_era5_land_climo -v tp"),
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
        default=2021,
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
