import argparse

import matplotlib.pyplot as plt

from plot_common import (
    all_interval_netcdf_paths,
    output_path_for_variable,
    parse_region_arg,
    plot_variable_across_files,
)
from plot_scales import SPI_USDM_SCALE

VARIABLE_KEY = "spi"
SCALE = SPI_USDM_SCALE


def main(region=None) -> None:
    plot_variable_across_files(
        all_interval_netcdf_paths(),
        variable_key=VARIABLE_KEY,
        scale=SCALE,
        region=region,
        save_path=output_path_for_variable(VARIABLE_KEY, region),
    )
    plt.close("all")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Plot {SCALE.indicator_title} across intervals."
    )
    parser.add_argument(
        "--region",
        choices=sorted(__import__("region_subset", fromlist=["REGIONS"]).REGIONS),
        default=None,
        help="Zoom to a predefined regional subset (e.g. interior_alaska)",
    )
    main(region=parse_region_arg(parser.parse_args().region))
