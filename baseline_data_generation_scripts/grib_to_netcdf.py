#!/usr/bin/env python3
"""Convert GRIB files in a flat directory to NetCDF.

Examples
--------
Serial conversion of a whole directory:
    python grib_dir_to_netcdf.py --input-dir /path/to/pr

Process only one indexed file (useful for SLURM array jobs):
    python grib_dir_to_netcdf.py --input-dir /path/to/pr --index 7
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import earthkit.data as ekd
import xarray as xr

NETCDF_ENGINE = "netcdf4"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Flat directory containing GRIB files.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Optional parent directory for the output folder. "
            "If omitted, output is written beside input as <input_name>_nc."
        ),
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help=(
            "Zero-based file index to process after sorting. "
            "Useful with SLURM_ARRAY_TASK_ID."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing NetCDF outputs.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def discover_grib_files(input_dir: Path) -> list[Path]:
    """Return sorted GRIB files in the target flat directory."""
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    files = sorted(
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".grib"
    )

    if not files:
        raise FileNotFoundError(f"No GRIB files found in {input_dir}")

    return files


def derive_output_dir(input_dir: Path, output_root: Path | None = None) -> Path:
    """Build the sibling output directory name."""
    out_name = f"{input_dir.name}_nc"
    return (output_root / out_name) if output_root else (input_dir.parent / out_name)


def sanitize_dataset(ds: xr.Dataset) -> xr.Dataset:
    """Remove Earthkit attrs and apply conservative renames."""
    ds.attrs.pop("_earthkit", None)

    for name in ds.variables:
        ds[name].attrs.pop("_earthkit", None)

    if (
        "forecast_reference_time" in ds.variables
        and "time" not in ds.variables
        and "time" not in ds.dims
    ):
        ds = ds.rename({"forecast_reference_time": "time"})

    return ds


def process_one_file(
    grib_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """Convert one GRIB file to one NetCDF file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{grib_path.stem}.nc"
    tmp_path = output_dir / f"{grib_path.stem}.nc.part"

    if output_path.exists() and not overwrite:
        logging.info("Skipping existing file: %s", output_path)
        return output_path

    if tmp_path.exists():
        tmp_path.unlink()

    ds: xr.Dataset | None = None
    t0 = time.perf_counter()

    try:
        logging.info("Reading GRIB: %s", grib_path)
        fl = ekd.from_source("file", str(grib_path))

        with xr.set_options(keep_attrs=True):
            ds = fl.to_xarray(allow_holes=True)

        ds = sanitize_dataset(ds)

        logging.info("Writing NetCDF with engine=%s: %s", NETCDF_ENGINE, tmp_path)
        ds.to_netcdf(tmp_path, mode="w", engine=NETCDF_ENGINE)
        tmp_path.replace(output_path)

        elapsed = time.perf_counter() - t0
        logging.info("Finished %s in %.1f s", output_path.name, elapsed)
        return output_path

    except Exception:
        logging.exception("Failed converting %s", grib_path)
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    finally:
        if ds is not None:
            ds.close()


def main() -> int:
    """Run the conversion workflow."""
    args = parse_args()
    setup_logging()

    if args.index is None and "SLURM_ARRAY_TASK_ID" in os.environ:
        args.index = int(os.environ["SLURM_ARRAY_TASK_ID"])

    grib_files = discover_grib_files(args.input_dir)
    output_dir = derive_output_dir(args.input_dir, output_root=args.output_root)

    logging.info("Found %d GRIB files in %s", len(grib_files), args.input_dir)
    logging.info("Output directory: %s", output_dir)

    if args.index is not None:
        if args.index < 0 or args.index >= len(grib_files):
            raise IndexError(
                f"Index {args.index} is out of range for {len(grib_files)} files "
                f"in {args.input_dir}"
            )

        process_one_file(
            grib_path=grib_files[args.index],
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        return 0

    for grib_path in grib_files:
        process_one_file(
            grib_path=grib_path,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())