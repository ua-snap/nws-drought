#!/usr/bin/env python3
"""Build weighted soil moisture climatology from combined swvl1 and swvl2 daily NetCDFs."""

import argparse
import logging
import sys

import xarray as xr

from config import climo_file_for_var, daily_combined_file_for_var
from file_helpers import NETCDF_ENGINE, setup_logging

# Weights prescribed during initial dev work phase by Brian B
WEIGHT_LAYER1 = 0.25
WEIGHT_LAYER2 = 0.75


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read daily combined swvl1 and swvl2 NetCDFs, "
            "compute swvl = swvl1*WEIGHT_LAYER1 + swvl2*WEIGHT_LAYER2,"
            "write a day-of-year climatology for soil moisture."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Example:\n  python combine_soil_moisture_layers.py"),
    )
    return parser.parse_args()


def weighted_swvl_climatology(
    swvl1: xr.DataArray,
    swvl2: xr.DataArray,
) -> xr.DataArray:
    """Return day-of-year climatology of weighted soil moisture."""
    swvl1_a, swvl2_a = xr.align(swvl1, swvl2, join="inner")
    swvl = (swvl1_a * WEIGHT_LAYER1 + swvl2_a * WEIGHT_LAYER2).astype("float32")
    swvl.name = "swvl"
    clim = swvl.groupby("valid_time.dayofyear").mean(dim="valid_time")
    clim = clim.rename({"dayofyear": "time"})
    clim.name = "swvl"
    clim.attrs.setdefault(
        "long_name",
        "Daily climatological mean volumetric soil water (weighted layers 1-2)",
    )
    clim.attrs["layer_weights"] = f"swvl1*{WEIGHT_LAYER1} + swvl2*{WEIGHT_LAYER2}"
    clim["time"].attrs.setdefault("long_name", "day of year")
    clim["time"].attrs.setdefault("description", "calendar day of year (1-366)")
    return clim


def main() -> int:
    """Run weighted soil moisture climatology workflow."""
    args = parse_args()
    setup_logging()

    swvl1_file = daily_combined_file_for_var("swvl1")
    swvl2_file = daily_combined_file_for_var("swvl2")
    out_path = climo_file_for_var("swvl")
    logging.info("Resolved swvl1 input file: %s", swvl1_file)
    logging.info("Resolved swvl2 input file: %s", swvl2_file)
    logging.info("Resolved output file: %s", out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logging.info("Output already exists: %s", out_path)
        return 0

    ds1: xr.Dataset | None = None
    ds2: xr.Dataset | None = None
    try:
        if not swvl1_file.is_file():
            raise FileNotFoundError(f"swvl1 file not found: {swvl1_file}")
        if not swvl2_file.is_file():
            raise FileNotFoundError(f"swvl2 file not found: {swvl2_file}")

        ds1 = xr.open_dataset(swvl1_file, engine=NETCDF_ENGINE)
        ds2 = xr.open_dataset(swvl2_file, engine=NETCDF_ENGINE)
        if "swvl1" not in ds1.data_vars:
            raise ValueError(
                f"Expected data variable 'swvl1' in {swvl1_file}, "
                f"found {list(ds1.data_vars)}"
            )
        if "swvl2" not in ds2.data_vars:
            raise ValueError(
                f"Expected data variable 'swvl2' in {swvl2_file}, "
                f"found {list(ds2.data_vars)}"
            )

        swvl1 = ds1["swvl1"]
        swvl2 = ds2["swvl2"]
        clim_da = weighted_swvl_climatology(swvl1, swvl2)
        out_ds = clim_da.to_dataset()
        out_ds.attrs["source"] = (
            "Weighted combination of swvl1 and swvl2 UTC daily means; "
            "day-of-year climatology (mean over time)."
        )

        out_ds.to_netcdf(
            out_path,
            engine=NETCDF_ENGINE,
            encoding={"swvl": {"dtype": "float32"}},
        )
        logging.info(
            "Wrote %s (%s day-of-year steps)", out_path, clim_da.sizes.get("time", 0)
        )
    finally:
        if ds2 is not None:
            ds2.close()
        if ds1 is not None:
            ds1.close()

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
