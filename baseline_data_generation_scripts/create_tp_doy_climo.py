#!/usr/bin/env python3
"""Build Total Precipitation DOY climatology from daily NetCDFs."""

import argparse
import logging
import sys

import xarray as xr
from config import baseline_climo_file, daily_combined_file_for_var

NETCDF_ENGINE = "h5netcdf"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read UTC-9 daily Total Precipitation NetCDF, then write "
            "a day-of-year climatology (dimension time = DOY 1-366)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def tp_climatology(
    tp: xr.DataArray,
) -> xr.DataArray:
    """Return day-of-year climatology of Total Precipitation."""
    tp.name = "tp"
    clim = tp.groupby("time.dayofyear").mean(dim="time")
    clim = clim.rename({"dayofyear": "time"})
    clim.name = "tp"
    clim.attrs.setdefault(
        "long_name",
        "Daily climatological mean total precipitation",
    )
    clim["time"].attrs.setdefault("long_name", "day of year")
    clim["time"].attrs.setdefault("description", "calendar day of year (1-366)")
    return clim


def main() -> int:
    """Run Total Precipitation DOY climatology workflow."""
    args = parse_args()
    setup_logging()

    tp_file = daily_combined_file_for_var("tp")
    out_path = baseline_climo_file("tp")
    logging.info("Resolved tp input file: %s", tp_file)
    logging.info("Resolved output file: %s", out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logging.info("Output already exists: %s", out_path)
        return 0

    ds: xr.Dataset | None = None
    try:
        if not tp_file.is_file():
            raise FileNotFoundError(f"Total Precipitation file not found: {tp_file}")

        ds = xr.open_dataset(tp_file, engine=NETCDF_ENGINE)
        if "tp" not in ds.data_vars:
            raise ValueError(
                f"Expected data variable 'tp' in {tp_file}, "
                f"found {list(ds.data_vars)}"
            )

        tp = ds["tp"]
        clim_da = tp_climatology(tp)
        out_ds = clim_da.to_dataset()
        out_ds.attrs["source"] = (
            "Total Precipitation UTC-9 daily means; "
            "day-of-year climatology (mean over time)."
        )

        out_ds.to_netcdf(
            out_path,
            engine=NETCDF_ENGINE,
            encoding={"tp": {"dtype": "float32"}},
        )
        logging.info(
            "Wrote %s (%s day-of-year steps)", out_path, clim_da.sizes.get("time", 0)
        )
    finally:
        if ds is not None:
            ds.close()

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
