"""Generate every drought map figure for one zoomed geographic subset.

For full-domain and multi-region batch runs, prefer ``plot_all.py``.
"""

import argparse

from plot_all import run_all_plots
from region_subset import REGIONS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all data_viz plotting scripts for a zoomed region."
    )
    parser.add_argument(
        "--region",
        choices=sorted(REGIONS),
        default="interior_alaska",
        help="Predefined subset (default: interior_alaska)",
    )
    args = parser.parse_args()
    run_all_plots(region=args.region)


if __name__ == "__main__":
    main()
