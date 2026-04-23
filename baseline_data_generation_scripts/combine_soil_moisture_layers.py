#!/usr/bin/env python3
"""Build weighted soil moisture climatology from combined swvl1 and swvl2 daily NetCDFs."""

import argparse
import logging
import sys
from pathlib import Path

import xarray as xr

NETCDF_ENGINE = "h5netcdf"
WEIGHT_LAYER1 = 0.25
WEIGHT_LAYER2 = 0.75


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read UTC-9 daily combined swvl1 and swvl2 NetCDFs, form "
            "swvl = swvl1*WEIGHT_LAYER1 + swvl2*WEIGHT_LAYER2, then write "
            "a day-of-year climatology (dimension time = DOY 1-366) for "
            "pipeline.process.process_smd."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python combine_soil_moisture_layers.py \\\n"
            "    --swvl1-file drought_climatology_baselines/"
            "swvl1_daily_utc_minus9_combined.nc \\\n"
            "    --swvl2-file drought_climatology_baselines/"
            "swvl2_daily_utc_minus9_combined.nc \\\n"
            "    --output-file drought_climatology_baselines/"
            "era5_daily_swvl_1981_2020.nc"
        ),
    )
    parser.add_argument(
        "--swvl1-file",
        type=Path,
        required=True,
        help="Combined daily NetCDF for swvl1 (variable name swvl1).",
    )
    parser.add_argument(
        "--swvl2-file",
        type=Path,
        required=True,
        help="Combined daily NetCDF for swvl2 (variable name swvl2).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Output NetCDF path (e.g. era5_daily_swvl_1981_2020.nc).",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def weighted_swvl_climatology(
    swvl1: xr.DataArray,
    swvl2: xr.DataArray,
) -> xr.DataArray:
    """Return day-of-year climatology of weighted soil moisture."""
    swvl1_a, swvl2_a = xr.align(swvl1, swvl2, join="inner")
    swvl = (swvl1_a * WEIGHT_LAYER1 + swvl2_a * WEIGHT_LAYER2).astype("float32")
    swvl.name = "swvl"
    clim = swvl.groupby("time.dayofyear").mean(dim="time")
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

    out_path = args.output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logging.info("Output already exists: %s", out_path)
        return 0

    ds1: xr.Dataset | None = None
    ds2: xr.Dataset | None = None
    try:
        if not args.swvl1_file.is_file():
            raise FileNotFoundError(f"swvl1 file not found: {args.swvl1_file}")
        if not args.swvl2_file.is_file():
            raise FileNotFoundError(f"swvl2 file not found: {args.swvl2_file}")

        ds1 = xr.open_dataset(args.swvl1_file, engine=NETCDF_ENGINE)
        ds2 = xr.open_dataset(args.swvl2_file, engine=NETCDF_ENGINE)
        if "swvl1" not in ds1.data_vars:
            raise ValueError(
                f"Expected data variable 'swvl1' in {args.swvl1_file}, "
                f"found {list(ds1.data_vars)}"
            )
        if "swvl2" not in ds2.data_vars:
            raise ValueError(
                f"Expected data variable 'swvl2' in {args.swvl2_file}, "
                f"found {list(ds2.data_vars)}"
            )

        swvl1 = ds1["swvl1"]
        swvl2 = ds2["swvl2"]
        logging.info(
            "Aligning swvl1 time (%s steps) with swvl2 (%s steps) (inner join)",
            swvl1.sizes.get("time", 0),
            swvl2.sizes.get("time", 0),
        )
        clim_da = weighted_swvl_climatology(swvl1, swvl2)
        out_ds = clim_da.to_dataset()
        out_ds.attrs["source"] = (
            "Weighted combination of swvl1 and swvl2 UTC-9 daily means; "
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
