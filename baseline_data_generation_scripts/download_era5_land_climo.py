"""Build the ERA5-Land climatology (1981-2020) from the DestinE Earth Data Hub
mirror, for every variable or the variables given with --variable.

Needs an Earth Data Hub API key in EDH_API_KEY and the `mirror` dependency group.
Yearly files the mirror already built are kept, so running this again after a stop
continues where it stopped. Each CDS-built yearly file is moved to the climatology
archive just before its mirror replacement is written.
"""

import argparse
import logging
import sys

from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import setup_logging
from mirror_climatology import (
    CLIMATOLOGY_END_YEAR,
    CLIMATOLOGY_START_YEAR,
    ArchiveClash,
    MirrorKeyMissing,
    MirrorUnavailable,
    download_era5_land_climatology,
)


def main() -> None:
    choices = sorted(VARIABLE_REGISTRY.keys())
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Examples:\n"
            "  uv run --frozen --group mirror python -m "
            "baseline_data_generation_scripts.download_era5_land_climo\n"
            "  uv run --frozen --group mirror python -m "
            "baseline_data_generation_scripts.download_era5_land_climo "
            "--start-year 2000 --end-year 2000"
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
        default=CLIMATOLOGY_START_YEAR,
        help="First calendar year to build (inclusive).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=CLIMATOLOGY_END_YEAR,
        help="Last calendar year to build (inclusive).",
    )
    args = parser.parse_args()

    setup_logging()
    try:
        download_era5_land_climatology(
            args.variables,
            start_year=args.start_year,
            end_year=args.end_year,
        )
    except (MirrorKeyMissing, MirrorUnavailable, ArchiveClash) as exc:
        logging.getLogger(__name__).error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
