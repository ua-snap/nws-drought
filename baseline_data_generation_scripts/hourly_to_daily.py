#!/usr/bin/env python3
"""Build UTC-9 daily annual NetCDF files from hourly ERA5-Land GRIB.

This script expects a flat directory of yearly GRIB files, one per year.

Variables and daily reductions:
- tp     : daily total (sum, forecast accumulated)
- pev    : daily total (sum, forecast accumulated)
- swe    : daily mean
- swvl1  : daily mean
- swvl2  : daily mean

Input filenames are variable-specific:

    tp     -> total_precipitation_hourly_YYYY.grib
    pev    -> potential_evaporation_hourly_YYYY.grib
    swe    -> snow_water_equivalent_hourly_YYYY.grib
    swvl1  -> volumetric_soil_water_level_1_hourly_YYYY.grib
    swvl2  -> volumetric_soil_water_level_2_hourly_YYYY.grib

It computes daily values for the UTC-9 local-day window:
    [09:00 UTC on day D, 09:00 UTC on day D+1)

Output time stamps are kept in UTC and represent the START of that 24-hour window,
so a local day labeled 1982-01-01 becomes:
    time = 1982-01-01 09:00:00 UTC

Notes
-----
This script has two different daily-construction paths:

1. Forecast accumulated variables (`tp`, `pev`)
   ERA5-Land stores these as cumulative totals since 00 UTC, so daily sums for
   a non-UTC timezone must be reconstructed from specific forecast hours.

2. Instantaneous/state variables (`swe`, `swvl1`, `swvl2`)
   These are valid-at-time hourly values, so daily means are computed by
   assigning each hourly timestamp to its UTC-9 local day and averaging over
   complete 24-hour windows.

For forecast-style accumulated variables (tp, pev):
    local_total(D) = utc_day_total(D) - cum_00_to_09(D) + cum_00_to_09(D+1)

where for UTC-9:
- utc_day_total(D) comes from valid_time = D+1 00:00 UTC
- cum_00_to_09(D) comes from valid_time = D 09:00 UTC
- cum_00_to_09(D+1) comes from valid_time = D+1 09:00 UTC

For mean variables (swe, swvl1, swvl2), the same UTC-9 day window is averaged
over available hourly values.

Examples
--------
python hourly_to_daily.py \
    --var tp \
    --year 1982

python hourly_to_daily.py \
    --var pev
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import xarray as xr
from config import daily_year_dir_for_var, hourly_dir_for_var

# We want daily windows in UTC-9 local time.
# Local midnight in UTC-9 occurs at 09:00 UTC, so each local day is represented
# by the half-open UTC interval [09:00 UTC on day D, 09:00 UTC on day D+1).
WINDOW_START_UTC_HOUR = 9
# GRIB year used only to pad the trailing UTC-9 local day of the prior year (e.g.
# 2020-12-31 needs 2021-01-01 00/09 UTC). No annual NetCDF is written for this year.
BOUNDARY_PADDING_YEAR = 2021
NETCDF_ENGINE = "h5netcdf"
_INPUT_NAME_SUFFIX = ".grib"
# Central variable registry:
# - input_prefix: filename prefix used to discover yearly GRIB files
# - source_var: shortName exposed by cfgrib inside the GRIB file
# - daily_op: how the daily statistic should be constructed
#   * "sum"  -> ERA5-Land forecast accumulations (tp, pev)
#   * "mean" -> ERA5-Land instantaneous/state variables (swe, swvl1, swvl2)
# - long_name: output metadata for the daily NetCDF
#
# This split matters because ERA5-Land stores accumulated variables very
# differently from state variables:
# - accumulations are forecast-style cumulative totals since 00 UTC
# - state variables are instantaneous values valid at each hour
VAR_CONFIG = {
    "tp": {
        "input_prefix": "total_precipitation_hourly_",
        "source_var": "tp",
        "daily_op": "sum",
        "long_name": "Daily total precipitation for UTC-9 local-day window",
    },
    "pev": {
        "input_prefix": "potential_evaporation_hourly_",
        "source_var": "pev",
        "daily_op": "sum",
        "long_name": "Daily total potential evaporation for UTC-9 local-day window",
    },
    "swe": {
        "input_prefix": "snow_water_equivalent_hourly_",
        "source_var": "sd",
        "daily_op": "mean",
        "long_name": "Daily mean snow water equivalent for UTC-9 local-day window",
    },
    "swvl1": {
        "input_prefix": "volumetric_soil_water_level_1_hourly_",
        "source_var": "swvl1",
        "daily_op": "mean",
        "long_name": "Daily mean volumetric soil water layer 1 for UTC-9 local-day window",
    },
    "swvl2": {
        "input_prefix": "volumetric_soil_water_level_2_hourly_",
        "source_var": "swvl2",
        "daily_op": "mean",
        "long_name": "Daily mean volumetric soil water layer 2 for UTC-9 local-day window",
    },
}
SUPPORTED_VARS = set(VAR_CONFIG)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--var",
        type=str,
        required=True,
        choices=sorted(SUPPORTED_VARS),
        help="Variable to process.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "Optional single year to process. If omitted, all discovered years are "
            "processed."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _year_from_input_filename(name: str, *, prefix: str) -> int:
    """Parse calendar year from ``<prefix>YYYY.grib``."""
    # CP note: finding that defensive coding is useful when submitting via SLURM
    if not (name.startswith(prefix) and name.endswith(_INPUT_NAME_SUFFIX)):
        raise ValueError(f"Expected filename like {prefix}1993.grib, got {name!r}")
    year = name[len(prefix) : -len(_INPUT_NAME_SUFFIX)]
    if len(year) != 4 or not year.isdecimal():
        raise ValueError(f"Expected filename like {prefix}1993.grib, got {name!r}")
    return int(year)


def discover_year_files(input_dir: Path, *, varname: str) -> dict[int, Path]:
    """Discover yearly GRIB files for the selected variable."""
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    prefix = VAR_CONFIG[varname]["input_prefix"]
    paths = sorted(p for p in input_dir.glob(f"{prefix}*.grib") if p.is_file())
    if not paths:
        raise FileNotFoundError(
            f"No files matching {prefix}*.grib found in {input_dir}"
        )

    year_to_path: dict[int, Path] = {}
    for path in paths:
        year = _year_from_input_filename(path.name, prefix=prefix)
        if year in year_to_path:
            raise ValueError(
                f"Multiple files appear to map to year {year}: "
                f"{year_to_path[year].name}, {path.name}"
            )
        year_to_path[year] = path

    return dict(sorted(year_to_path.items()))


def open_hourly_dataset(path: Path, *, varname: str) -> xr.Dataset:
    """Open one ERA5-Land GRIB file with a 1D valid_time axis.

    Args:
        path: Path to the GRIB file.
        varname: The variable name to open.

    Returns:
        A xr.Dataset with the variable name as the data variable.
    """
    ds = xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={
            "time_dims": ["valid_time"],
            "coords_as_attributes": ["surface", "number"],
            "indexpath": "",  # grib will make some auxiliary files that we don't need
        },
    )

    source_var = VAR_CONFIG[varname]["source_var"]
    if source_var not in ds.data_vars:
        ds.close()
        raise ValueError(
            f"Expected GRIB variable {source_var!r} for requested --var {varname!r} "
            f"in {path.name}, "
            f"found {list(ds.data_vars)}"
        )

    # cfgrib exposes ERA5-Land variables using GRIB shortNames (for example, SWE
    # is "sd" in the file, not "swe"). Rename here so the rest of the pipeline
    # can use the swe variable name consistently.
    out = ds[[source_var]].rename({source_var: varname}).sortby("valid_time")

    # Remove attrs that are noisy or backend-specific.
    out.attrs.pop("history", None)

    return out


def subset_hour(ds: xr.Dataset, hour: int) -> xr.Dataset:
    """Subset a valid_time-indexed dataset to a specific UTC hour.

    For ERA5-Land accumulated forecast variables we only need two validity times:
    - 00 UTC: contains the full accumulation from the previous UTC day
    - local midnight expressed in UTC (09 UTC for UTC-9): used to split that
      UTC-day accumulation into the requested local-day window

    That is why the accumulation workflow samples only 00 UTC and 09 UTC rather
    than summing all 24 hourly forecast records.
    """
    return ds.where(ds.valid_time.dt.hour == hour, drop=True)


def relabel_to_local_date(ds: xr.Dataset, day_offset: int) -> xr.Dataset:
    """Relabel valid_time to a local_date coordinate with an integer day offset.

    Examples
    --------
    For valid_time = 1982-01-02 00:00 and day_offset = -1,
    local_date becomes 1982-01-01.
    """
    # We relabel by "local_date" rather than keeping the original valid_time
    # because the arithmetic is easier to reason about in local-day space. For
    # example, the accumulation valid at 1982-01-02 00 UTC belongs to the UTC
    # day 1982-01-01, which in turn contributes to the local day labeled
    # 1982-01-01.
    local_dates = ds.valid_time.values.astype("datetime64[D]") + np.timedelta64(
        day_offset, "D"
    )
    out = ds.assign_coords(local_date=("valid_time", local_dates))
    out = out.swap_dims({"valid_time": "local_date"}).drop_vars("valid_time")
    return out.sortby("local_date")


def first_hour_record(ds: xr.Dataset, hour: int) -> xr.Dataset:
    """Return the first available record for a given UTC hour.

    Args:
        ds: The xr.Dataset to subset.
        hour: The UTC hour to subset.

    Returns:
        A xr.Dataset with the first available record for the given UTC hour.
    """
    hour_ds = subset_hour(ds, hour)
    if hour_ds.sizes.get("valid_time", 0) == 0:
        raise ValueError(f"No valid_time values found for UTC hour {hour}")
    return hour_ds.isel(valid_time=slice(0, 1))


def intersect_dates(*arrays: np.ndarray) -> np.ndarray:
    """Return the sorted intersection of multiple datetime64[D] arrays.

    Args:
        *arrays: The datetime64[D] arrays to intersect.

    Returns:
        A numpy array of the sorted intersection of the input arrays.
    """
    if not arrays:
        raise ValueError("At least one date array is required.")
    common = arrays[0]
    for arr in arrays[1:]:
        common = np.intersect1d(common, arr)
    return np.sort(common)


def _target_dates_for_year(year: int) -> np.ndarray:
    """Return contiguous calendar dates for a target year.

    Args:
        year: The year to return the contiguous calendar dates for.

    Returns:
        A numpy array of the contiguous calendar dates for the target year.
    """
    return np.arange(
        np.datetime64(f"{year}-01-01"),
        np.datetime64(f"{year + 1}-01-01"),
        np.timedelta64(1, "D"),
    )


def _finalize_daily_dataset(
    *,
    varname: str,
    daily: xr.Dataset,
    common_dates: np.ndarray,
) -> xr.Dataset:
    """Attach standardized coordinates and metadata for daily outputs."""
    # We keep output timestamps in UTC, but we label each record by the UTC
    # start of the local-day window. For UTC-9, the local day "1982-01-01"
    # starts at 1982-01-01 09:00 UTC, so that becomes the output time
    # coordinate.
    utc_start_times = common_dates + np.timedelta64(WINDOW_START_UTC_HOUR, "h")
    daily = daily.assign_coords(time=("local_date", utc_start_times))
    daily = daily.swap_dims({"local_date": "time"}).sortby("time")
    daily = daily.assign_coords(local_date=("time", common_dates))

    daily[varname].attrs["long_name"] = VAR_CONFIG[varname]["long_name"]
    daily[varname].attrs["aggregation_window"] = "09:00 UTC to 09:00 UTC next day"
    daily[varname].attrs[
        "time_coordinate_meaning"
    ] = "UTC start timestamp of the 24-hour UTC-9 daily aggregation window"
    daily[varname].attrs["local_timezone_offset"] = "UTC-9"
    daily.attrs["source"] = "ERA5-Land hourly GRIB"

    if VAR_CONFIG[varname]["daily_op"] == "sum":
        daily.attrs["processing"] = (
            "daily_total = utc_day_total - cum_00_to_09 + next_00_to_09"
        )
    else:
        daily.attrs["processing"] = (
            "daily_mean = mean(hourly values in UTC-9 window [09:00, 09:00))"
        )

    return daily


def compute_one_year_sum(
    varname: str,
    year: int,
    current_path: Path,
    next_path: Path | None,
) -> xr.Dataset:
    """Compute one year of UTC-9 daily totals for forecast accumulated variables."""
    current_ds: xr.Dataset | None = None
    next_ds: xr.Dataset | None = None

    try:
        logging.info("Opening current year: %s", current_path.name)
        current_ds = open_hourly_dataset(current_path, varname=varname)

        # ERA5-Land accumulated variables are not stored as "one independent
        # value per hour". Instead, each forecast hour contains the running
        # total since 00 UTC.
        #
        # Here, D means the local calendar day we want to compute. For example,
        # if we are building the UTC-9 local day labeled 1982-01-01, then
        # D = 1982-01-01.
        #
        # For that local day, we need three pieces:
        # - D+1 00 UTC: the full accumulation over UTC day D
        # - D 09 UTC: the running total from D 00 UTC to D 09 UTC
        # - D+1 09 UTC: the running total from D+1 00 UTC to D+1 09 UTC
        #
        # We start with the full UTC-day total for D, remove the early hours
        # before local midnight on D, then add the early hours after local
        # midnight on D+1. This is why we sample only 00 UTC and 09 UTC rather
        # than summing all 24 hourly forecast records.
        current_00 = subset_hour(current_ds, 0)
        current_09 = subset_hour(current_ds, WINDOW_START_UTC_HOUR)

        # After relabeling:
        # - utc_day_total(local_date=D)   = accumulation over UTC day D
        # - cum_00_to_09(local_date=D)    = accumulation from D 00 UTC to D 09 UTC
        # - next_00_to_09(local_date=D)   = accumulation from D+1 00 UTC to
        #                                   D+1 09 UTC
        #
        # Then local_day_total(D) = utc_day_total(D) - cum_00_to_09(D)
        #                         + next_00_to_09(D)
        utc_day_total = relabel_to_local_date(current_00, day_offset=-1)
        cum_00_to_09 = relabel_to_local_date(current_09, day_offset=0)
        next_00_to_09 = relabel_to_local_date(current_09, day_offset=-1)

        if next_path is not None:
            # The final local day of a year extends into the next calendar year
            # because the UTC-9 day ends at 09:00 UTC on January 1 of the
            # following year. We therefore need the first 00 UTC and 09 UTC
            # records from year+1 to finish the trailing edge of the last local
            # day.
            logging.info("Opening next year for boundary padding: %s", next_path.name)
            next_ds = open_hourly_dataset(next_path, varname=varname)

            next_00_first = relabel_to_local_date(
                first_hour_record(next_ds, 0), day_offset=-1
            )
            next_09_first = relabel_to_local_date(
                first_hour_record(next_ds, WINDOW_START_UTC_HOUR),
                day_offset=-1,
            )

            utc_day_total = xr.concat([utc_day_total, next_00_first], dim="local_date")
            next_00_to_09 = xr.concat([next_00_to_09, next_09_first], dim="local_date")

        target_dates = _target_dates_for_year(year)
        # Only keep dates for which all required pieces exist. This prevents us
        # from constructing a local-day accumulation from incomplete boundary
        # information.
        common_dates = intersect_dates(
            target_dates,
            utc_day_total.local_date.values,
            cum_00_to_09.local_date.values,
            next_00_to_09.local_date.values,
        )
        if common_dates.size == 0:
            raise ValueError(f"No daily dates could be computed for year {year}.")

        expected_days = len(target_dates)
        if common_dates.size != expected_days:
            missing_days = expected_days - common_dates.size
            logging.warning(
                "Year %s is missing %d day(s). This usually means the next year's "
                "file is not available for trailing-edge padding.",
                year,
                missing_days,
            )

        # This is the key ERA5-Land non-UTC accumulation formula:
        #   local_total(D) = utc_day_total(D) - cum_00_to_09(D) + next_00_to_09(D)
        #
        # Intuition:
        # - start with the full UTC day D total
        # - remove the part before local midnight (00->09 UTC on D)
        # - add the part after 24:00 local time that lives in the next UTC day
        #   (00->09 UTC on D+1)
        daily = (
            utc_day_total.sel(local_date=common_dates)
            - cum_00_to_09.sel(local_date=common_dates)
            + next_00_to_09.sel(local_date=common_dates)
        )
        return _finalize_daily_dataset(
            varname=varname,
            daily=daily,
            common_dates=common_dates,
        )
    finally:
        if next_ds is not None:
            next_ds.close()
        if current_ds is not None:
            current_ds.close()


def compute_one_year_mean(
    varname: str,
    year: int,
    current_path: Path,
    next_path: Path | None,
) -> xr.Dataset:
    """Compute one year of UTC-9 daily means for hourly state variables.

    Only complete 24-hour UTC-9 local days are retained.
    """
    current_ds: xr.Dataset | None = None
    next_ds: xr.Dataset | None = None
    merged: xr.Dataset | None = None

    try:
        logging.info("Opening current year: %s", current_path.name)
        # State variables are instantaneous values, not forecast accumulations.
        # For these variables the correct daily statistic is a mean of the
        # hourly values falling inside the UTC-9 local-day window
        # [09:00 UTC, 09:00 UTC next day). Unlike tp/pev, no
        # cumulative-forecast arithmetic is needed.
        current_ds = open_hourly_dataset(current_path, varname=varname)
        merged = current_ds

        if next_path is not None:
            # We append only the early hours of the next year so the final local
            # day of the current year can include its full trailing edge through
            # 09:00 UTC on Jan 1 of the next year.
            logging.info("Opening next year for boundary padding: %s", next_path.name)
            next_ds = open_hourly_dataset(next_path, varname=varname)
            next_cutoff = np.datetime64(f"{year + 1}-01-01T09:00:00")
            next_head = next_ds.where(next_ds.valid_time < next_cutoff, drop=True)
            if next_head.sizes.get("valid_time", 0) > 0:
                merged = xr.concat([current_ds, next_head], dim="valid_time").sortby(
                    "valid_time"
                )

        # Convert each UTC validity time into the local day it belongs to by
        # shifting the clock back by the UTC offset of local midnight. For UTC-9:
        # - 1982-01-01 09 UTC -> local_date 1982-01-01
        # - 1982-01-02 08 UTC -> local_date 1982-01-01
        # - 1982-01-02 09 UTC -> local_date 1982-01-02
        #
        # This is the instantaneous/state-variable analogue of ECMWF's
        # "time_shift" daily statistics logic.
        shifted_dates = (
            merged.valid_time.values - np.timedelta64(WINDOW_START_UTC_HOUR, "h")
        ).astype("datetime64[D]")
        merged = merged.assign_coords(local_date=("valid_time", shifted_dates))

        target_dates = _target_dates_for_year(year)
        merged = merged.where(merged.local_date.isin(target_dates), drop=True)
        # ECMWF's daily-statistics workflow removes partial periods. We do the
        # same here: only retain local days with all 24 hourly values, so a
        # daily mean is never computed from an incomplete sample.
        counts = merged[varname].groupby("local_date").count(dim="valid_time")
        # Counts are per (local_date, ...) and include latitude/longitude for
        # gridded fields. xarray counts non-NaN values; all-NaN cells (e.g. ocean
        # on SWE) have count 0 and must not veto the day. Partial days (1–23) do.
        per_cell_complete = (counts == 24) | (counts == 0)
        spatial_dims = tuple(d for d in counts.dims if d != "local_date")
        if spatial_dims:
            day_complete = per_cell_complete.all(dim=spatial_dims)
        else:
            day_complete = per_cell_complete
        complete_dates = day_complete.where(
            day_complete, drop=True
        ).local_date.values.astype("datetime64[D]")
        merged = merged.where(merged.local_date.isin(complete_dates), drop=True)
        # Once each hourly value has been assigned to its local day, the daily
        # mean is just the arithmetic mean over the 24 hourly samples in that
        # UTC-9 day window.
        daily = merged.groupby("local_date").mean(dim="valid_time")
        common_dates = daily.local_date.values.astype("datetime64[D]")

        if common_dates.size == 0:
            raise ValueError(f"No daily dates could be computed for year {year}.")

        expected_days = len(target_dates)
        if common_dates.size != expected_days:
            missing_days = expected_days - common_dates.size
            logging.warning(
                "Year %s is missing %d day(s). This usually means the next year's "
                "file is not available for trailing-edge padding or one or more "
                "hourly timesteps are missing.",
                year,
                missing_days,
            )

        return _finalize_daily_dataset(
            varname=varname,
            daily=daily,
            common_dates=common_dates,
        )
    finally:
        if merged is not None and merged is not current_ds:
            merged.close()
        if next_ds is not None:
            next_ds.close()
        if current_ds is not None:
            current_ds.close()


def compute_one_year(
    varname: str,
    year: int,
    current_path: Path,
    next_path: Path | None,
) -> xr.Dataset:
    """Compute one year of UTC-9 daily values for the selected variable."""
    if VAR_CONFIG[varname]["daily_op"] == "sum":
        return compute_one_year_sum(
            varname=varname,
            year=year,
            current_path=current_path,
            next_path=next_path,
        )
    return compute_one_year_mean(
        varname=varname,
        year=year,
        current_path=current_path,
        next_path=next_path,
    )


def write_annual_file(
    ds: xr.Dataset,
    output_path: Path,
    *,
    varname: str,
    overwrite: bool,
) -> Path:
    """Write one annual NetCDF file."""
    if output_path.exists():
        if not overwrite:
            logging.info("Skipping existing annual file: %s", output_path)
            return output_path
        output_path.unlink()

    ds.to_netcdf(
        output_path,
        engine=NETCDF_ENGINE,
        encoding={varname: {"dtype": "float32"}},
    )
    logging.info("Wrote annual file: %s", output_path)
    return output_path


def main() -> int:
    """Run annual file generation workflow."""
    args = parse_args()
    setup_logging()

    input_dir = hourly_dir_for_var(args.var)
    output_dir = daily_year_dir_for_var(args.var)
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Resolved input directory: %s", input_dir)
    logging.info("Resolved output directory: %s", output_dir)

    year_to_path = discover_year_files(input_dir, varname=args.var)
    discovered_years = sorted(year_to_path)

    if not discovered_years:
        raise RuntimeError("No yearly GRIB files were discovered.")

    logging.info(
        "Discovered %d yearly GRIB files spanning %s to %s",
        len(discovered_years),
        discovered_years[0],
        discovered_years[-1],
    )

    if args.year is not None:
        if args.year == BOUNDARY_PADDING_YEAR:
            raise ValueError(
                f"Year {BOUNDARY_PADDING_YEAR} is only used as boundary padding for "
                f"{BOUNDARY_PADDING_YEAR - 1}; no annual NetCDF is produced. "
                f"Use --year {BOUNDARY_PADDING_YEAR - 1} or omit --year."
            )
        if args.year not in year_to_path:
            raise ValueError(
                f"Requested --year {args.year} but no matching input file was found."
            )
        years_to_process = [args.year]
        logging.info("Processing single requested year: %s", args.year)
    else:
        years_to_process = [y for y in discovered_years if y != BOUNDARY_PADDING_YEAR]
        logging.info(
            "Processing all discovered years (excluding boundary-only %s).",
            BOUNDARY_PADDING_YEAR,
        )

    for year in years_to_process:
        current_path = year_to_path[year]
        next_path = year_to_path.get(year + 1)

        ds_year = compute_one_year(
            varname=args.var,
            year=year,
            current_path=current_path,
            next_path=next_path,
        )

        annual_path = output_dir / f"{args.var}_daily_utc_minus9_{year}.nc"
        write_annual_file(
            ds=ds_year,
            output_path=annual_path,
            varname=args.var,
            overwrite=args.overwrite,
        )
        ds_year.close()

        if next_path is None:
            logging.warning(
                "No %s file was found, so the final UTC-9 local day of %s "
                "cannot be computed. Output for that year will end one day early.",
                year + 1,
                year,
            )

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
