"""Derive statistical distribution parameters for SPI or SPEI calibration.

The compute subcommand estimates parameters for one summary interval. Intended
for SLURM array tasks where each task writes one intermediate NetCDF file per interval.

The merge subcommand combines the intermediate interval files into the
single output used by the drought indicator pipeline.
"""

import argparse
import logging
from pathlib import Path

import xarray as xr
from scipy.stats import rv_continuous
from xclim.indices.stats import fit

from config import (
    INTERVALS,
    SPEI_DIST,
    SPI_DIST,
    WATER_BUDGET_OFFSET_M,
    _require_supported_index,
    daily_combined_file_for_var,
    statistical_rv_output_file_for_index,
    statistical_rv_partial_dir_for_index,
)
from file_helpers import NETCDF_ENGINE, setup_logging


def estimate_params(
    da: xr.DataArray, window: int, distribution: str | rv_continuous
) -> xr.DataArray:
    """Run the parameter estimation for one interval.

    Includes summarizing the data to a moving average before estimating the parameters
    of the specified continuous random variable distribution along the time axis (year, essentially) for each day of the year.

    Args:
        da (xarray.DataArray): daily values, either precip or water budget, for all years in the climatology period.
        window (int): number of days over which to compute moving averages, i.e. the "time scale" of the algorithm.

    Returns:
        params (xarray.DataArray): parameter estimates computed over the time dimension for each day of the year
    """
    # computing rolling means
    roll_da = da.rolling(valid_time=window).mean(skipna=False, keep_attrs=True)
    # estimate parameters of the distribution fit to yearly values for each day of the year
    params = roll_da.groupby("valid_time.dayofyear").map(
        lambda x: fit(x, distribution, "APP", dim="valid_time")
    )
    params = params.assign_coords(interval=window).expand_dims(interval=1)
    return params


def load_calibration_array(index: str) -> xr.DataArray:
    """Load daily calibration data for the requested drought index.

    Args:
        index: Either "spi" or "spei".
    Returns:
        Daily precip or shifted water-budget values for the calibration period.
    """
    logging.info("Reading in precipitation data...")
    tp_cal_ds = xr.load_dataset(daily_combined_file_for_var("tp"))
    logging.info("Completed precip data read.")

    if index == "spi":
        return tp_cal_ds["tp"]

    logging.info("Reading in potential evapotransipiration data...")
    pev_cal_ds = xr.load_dataset(daily_combined_file_for_var("pev"))
    logging.info("Completed potential evapotransipiration data read.")

    # Water balance is pr - pet. PET (pev) in ERA5 is usually negative because
    # upward fluxes are negative, so adding pev gives the water budget.
    wb = tp_cal_ds["tp"] + pev_cal_ds["pev"]

    # If using a distribution strictly bounded by zero (like Gamma with loc=0),
    # the water budget must be shifted to be positive.
    # Currently, WATER_BUDGET_OFFSET_M is 0.00 because the Fisk distribution
    # is fit with an estimated location parameter, natively supporting negative values.
    wb += WATER_BUDGET_OFFSET_M
    wb.name = "wb"

    return wb


def compute_interval(
    index: str,
    interval: int,
    output: Path,
) -> Path:
    """Estimate and write statistical distribution parameters for one summary interval."""
    if interval not in INTERVALS:
        raise ValueError(
            f"Unsupported interval {interval}; expected one of {INTERVALS}"
        )

    da = load_calibration_array(index)

    logging.info(f"Estimating parameters for interval {interval}...")

    if index == "spei":
        da = estimate_params(da, interval, SPEI_DIST)
    elif index == "spi":
        da = estimate_params(da, interval, SPI_DIST)
    else:
        _require_supported_index(index)

    da.name = "params"
    da = da.astype("float32")
    params_ds = da.to_dataset()
    logging.info(f"Estimating parameters for interval {interval} complete.")

    output.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Writing interval output: {output}")
    params_ds.to_netcdf(output, engine=NETCDF_ENGINE)
    logging.info(f"All done for interval {interval}")

    return output


def partial_path(partial_dir: Path, index: str, interval: int) -> Path:
    """Build the intermediate output path for one interval."""
    if index == "spi":
        return partial_dir / f"{index}_{SPI_DIST}_parameters_interval_{interval:03d}.nc"
    return partial_dir / f"{index}_{SPEI_DIST}_parameters_interval_{interval:03d}.nc"


def merge_intervals(index: str, partial_dir: Path, output: Path) -> Path:
    """Merge per-interval parameter files into the final NetCDF."""
    paths = [partial_path(partial_dir, index, interval) for interval in INTERVALS]
    missing = [path for path in paths if not path.exists()]

    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing interval files:\n{missing_text}")

    logging.info(f"Merging interval files from {partial_dir}...")

    datasets = [xr.load_dataset(path) for path in paths]
    da = xr.concat(
        [ds["params"] for ds in datasets],
        dim="interval",
    ).sortby("interval")
    da.name = "params"
    params_ds = da.astype("float32").to_dataset()

    output.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Writing merged output: {output}...")
    params_ds.to_netcdf(output, engine=NETCDF_ENGINE)
    logging.info(f"Done writing merged {index} file.")

    for dataset in datasets:
        dataset.close()
    params_ds.close()
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
        help="Summary interval to process.",
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
        partial_dir = statistical_rv_partial_dir_for_index(args.index)
        output = partial_path(partial_dir, args.index, args.interval)
        logging.info(f"Resolved interval output path {output}")
        compute_interval(args.index, args.interval, output)
    elif args.command == "merge":
        partial_dir = statistical_rv_partial_dir_for_index(args.index)
        output = statistical_rv_output_file_for_index(args.index)
        logging.info(f"Resolved partial directory: {partial_dir}")
        logging.info(f"Resolved merged output path: {output}")
        merge_intervals(args.index, partial_dir, output)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
