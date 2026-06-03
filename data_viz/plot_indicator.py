"""Plot a single drought indicator across summary intervals."""

import argparse
import matplotlib.pyplot as plt

from plot_common import (
    all_interval_netcdf_paths,
    output_path_for_variable,
    parse_region_arg,
    plot_variable_across_files,
)
from plot_scales import SCALES_BY_VARIABLE_KEY


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot a single drought-indicator variable across summary intervals."
    )
    parser.add_argument(
        "indicator",
        choices=sorted(SCALES_BY_VARIABLE_KEY),
        help="Drought indicator variable key (e.g., tp, spi, smd, etc.)",
    )
    parser.add_argument(
        "--region",
        choices=sorted(__import__("region_subset", fromlist=["REGIONS"]).REGIONS),
        default=None,
        help="Zoom to a predefined regional subset (e.g., interior_alaska)",
    )
    args = parser.parse_args()

    variable_key = args.indicator
    scale = SCALES_BY_VARIABLE_KEY[variable_key]
    region = parse_region_arg(args.region)

    plot_variable_across_files(
        all_interval_netcdf_paths(),
        variable_key=variable_key,
        scale=scale,
        region=region,
        save_path=output_path_for_variable(variable_key, region),
    )
    plt.close("all")


if __name__ == "__main__":
    main()
