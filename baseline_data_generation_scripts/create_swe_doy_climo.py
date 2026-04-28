#!/usr/bin/env python3
"""Build SWE DOY climatology from daily NetCDFs."""

import argparse
import logging
import sys
from pathlib import Path

import xarray as xr

NETCDF_ENGINE = "h5netcdf"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read UTC-9 daily SWE NetCDF, then write "
            "a day-of-year climatology (dimension time = DOY 1-366)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--swe-file",
        type=Path,
        required=True,
        help="Combined daily NetCDF for SWE (variable name swe).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Output NetCDF path (e.g. era5_swe_climo_1981_2020.nc).",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def swe_climatology(
    swe: xr.DataArray,
) -> xr.DataArray:
    """Return day-of-year climatology of SWE."""
    swe.name = "swe"
    clim = swe.groupby("time.dayofyear").mean(dim="time")
    clim = clim.rename({"dayofyear": "time"})
    clim.name = "swe"
    clim.attrs.setdefault(
        "long_name",
        "Daily climatological mean snow depth water equivalent",
    )
    clim["time"].attrs.setdefault("long_name", "day of year")
    clim["time"].attrs.setdefault("description", "calendar day of year (1-366)")
    return clim


def main() -> int:
    """Run SWE climatology workflow."""
    args = parse_args()
    setup_logging()

    out_path = args.output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logging.info("Output already exists: %s", out_path)
        return 0

    ds: xr.Dataset | None = None
    try:
        if not args.swe_file.is_file():
            raise FileNotFoundError(f"SWE file not found: {args.swe_file}")

        ds = xr.open_dataset(args.swe_file, engine=NETCDF_ENGINE)
        if "swe" not in ds.data_vars:
            raise ValueError(
                f"Expected data variable 'swe' in {args.swe_file}, "
                f"found {list(ds.data_vars)}"
            )

        swe = ds["swe"]
        clim_da = swe_climatology(swe)
        out_ds = clim_da.to_dataset()
        out_ds.attrs["source"] = (
            "SWE UTC-9 daily means; " "day-of-year climatology (mean over time)."
        )

        out_ds.to_netcdf(
            out_path,
            engine=NETCDF_ENGINE,
            encoding={"swe": {"dtype": "float32"}},
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
