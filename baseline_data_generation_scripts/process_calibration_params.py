"""Derive gamma parameters for SPI/SPEI calibration.

The compute subcommand estimates parameters for one interval. This is intended
for SLURM array tasks where each task writes one intermediate NetCDF file.

The merge subcommand combines the six intermediate interval files into the
single output used by the drought pipeline.
"""

import argparse
import logging
import time
from pathlib import Path

import xarray as xr
from config import (
    daily_combined_file_for_var,
    gamma_output_file_for_index,
    gamma_partial_dir_for_index,
)
from xclim.indices.stats import fit

INTERVALS = [7, 30, 60, 90, 180, 365]


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def estimate_params(da: xr.DataArray, window: int) -> xr.DataArray:
    """Run the parameter estimation for one interval.

    Includes summarizing the data to a moving average before estimating the parameters of a gamma distribution along the time axis (year, essentially) for each day of the year.

    Args:
        da (xarray.DataArray): daily values, either precip or water budget, for all years in the climatology period.
        window (int): number of days over which to compute moving averages, i.e. the "time scale" of SPI algorithm.

    Returns:
        params (xarray.DataArray): parameter estimates computed over the time dimension for each day of the year in da
    """
    # computing rolling means
    roll_da = da.rolling(time=window).mean(skipna=False, keep_attrs=True)
    # estimate parameters of gamma distribution fit to yearly values for each day of the year
    params = roll_da.groupby("time.dayofyear").map(lambda x: fit(x, "gamma", "APP"))
    params = params.assign_coords(interval=window).expand_dims(interval=1)

    return params


def load_calibration_array(index: str) -> xr.DataArray:
    """Load daily calibration data for the requested drought index.

    Args:
        index: Drought index name, either "spi" or "spei".
    Returns:
        Daily precip or shifted water-budget values for the calibration period.
    """
    logging.info("Reading in precip data")
    tic = time.perf_counter()
    tp_cal_ds = xr.load_dataset(daily_combined_file_for_var("tp"))
    logging.info(
        "done reading precip data, %.1fm",
        (time.perf_counter() - tic) / 60,
    )

    if index == "spi":
        return tp_cal_ds["tp"]

    logging.info("Reading in PET data")
    tic = time.perf_counter()
    pev_cal_ds = xr.load_dataset(daily_combined_file_for_var("pev"))
    logging.info(
        "done reading PET data, %.1fm",
        (time.perf_counter() - tic) / 60,
    )

    # Water balance is pr - pet. PET (pev) in ERA5 is usually negative because
    # upward fluxes are negative, so adding pev gives the water budget.
    wb = tp_cal_ds["tp"] + pev_cal_ds["pev"]

    # Gamma is bounded by zero: water budget must be shifted so only positive
    # values are allowed. See xclim code; 1 mm is used there, but 2 mm avoids
    # remaining negative values for 180- and 365-day intervals in this dataset.
    wb += 0.002
    wb.name = "wb"

    return wb


def compute_interval(
    index: str,
    interval: int,
    output: Path,
) -> Path:
    """Estimate and write gamma parameters for one interval."""
    if interval not in INTERVALS:
        raise ValueError(
            f"Unsupported interval {interval}; expected one of {INTERVALS}"
        )

    main_tic = time.perf_counter()
    da = load_calibration_array(index)

    logging.info("Estimating parameters for interval=%s", interval)
    tic = time.perf_counter()
    da = estimate_params(da, interval)
    da.name = "params"
    da = da.astype("float32")
    params_ds = da.to_dataset()
    logging.info(
        "done estimating interval=%s, %.1fm",
        interval,
        (time.perf_counter() - tic) / 60,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    logging.info("Writing interval output: %s", output)
    params_ds.to_netcdf(output)
    logging.info(
        "All done for interval=%s, total wall time: %.1fm",
        interval,
        (time.perf_counter() - main_tic) / 60,
    )

    return output


def partial_path(partial_dir: Path, index: str, interval: int) -> Path:
    """Build the intermediate output path for one interval."""
    return partial_dir / f"{index}_gamma_parameters_interval_{interval:03d}.nc"


def merge_intervals(index: str, partial_dir: Path, output: Path) -> Path:
    """Merge per-interval parameter files into the final NetCDF."""
    paths = [partial_path(partial_dir, index, interval) for interval in INTERVALS]
    missing = [path for path in paths if not path.exists()]

    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing interval files:\n{missing_text}")

    logging.info("Merging interval files from %s", partial_dir)
    tic = time.perf_counter()
    datasets = [xr.load_dataset(path) for path in paths]
    da = xr.concat(
        [ds["params"] for ds in datasets],
        dim="interval",
    ).sortby("interval")
    da.name = "params"
    params_ds = da.astype("float32").to_dataset()

    output.parent.mkdir(parents=True, exist_ok=True)
    logging.info("Writing merged output: %s", output)
    params_ds.to_netcdf(output)
    logging.info("done merging interval files, %.1fm", (time.perf_counter() - tic) / 60)

    for dataset in datasets:
        dataset.close()

    return output


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    compute = subparsers.add_parser("compute", help="Compute one interval")
    compute.add_argument(
        "-i",
        "--index",
        choices=["spi", "spei"],
        required=True,
        help="Index name.",
    )
    compute.add_argument(
        "--interval",
        type=int,
        choices=INTERVALS,
        required=True,
        help="Accumulation interval to process.",
    )

    merge = subparsers.add_parser("merge", help="Merge interval files")
    merge.add_argument(
        "-i",
        "--index",
        choices=["spi", "spei"],
        required=True,
        help="Index name.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the requested calibration parameter workflow."""
    setup_logging()
    args = parse_args()

    if args.command == "compute":
        partial_dir = gamma_partial_dir_for_index(args.index)
        output = partial_path(partial_dir, args.index, args.interval)
        logging.info("Resolved interval output path: %s", output)
        compute_interval(args.index, args.interval, output)
    elif args.command == "merge":
        partial_dir = gamma_partial_dir_for_index(args.index)
        output = gamma_output_file_for_index(args.index)
        logging.info("Resolved partial directory: %s", partial_dir)
        logging.info("Resolved merged output path: %s", output)
        merge_intervals(args.index, partial_dir, output)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
