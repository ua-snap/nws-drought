"""Download the ERA5-Land climatology (1981-2021) for every variable, or the
variables given with --variable.

Requests go to CDS one at a time. Yearly files that already pass their check
are kept, so running this again after a stop continues where it stopped.
"""

import argparse
import logging

from download_helpers import api_credentials_check, download_era5_land_climatology
from era5_land_variable_registry import VARIABLE_REGISTRY


def main() -> None:
    choices = sorted(VARIABLE_REGISTRY.keys())
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Examples:\n"
            "  python -m baseline_data_generation_scripts.download_era5_land_climo\n"
            "  python -m baseline_data_generation_scripts.download_era5_land_climo -v tp -v pev"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--variable",
        dest="variables",
        action="append",
        choices=choices,
        metavar="VAR",
        help=f"Variable key, repeatable (default: all of {', '.join(choices)})",
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
        args.variables,
        start_year=args.start_year,
        end_year=args.end_year,
    )


if __name__ == "__main__":
    main()
