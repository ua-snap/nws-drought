"""UTC-9 local-day daily statistics from ERA5-Land hourly GRIB."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import xarray as xr

from nws_drought.era5_land.grib import open_hourly_dataset
from nws_drought.era5_land.registry import VARIABLE_REGISTRY

# Local midnight in UTC-9 occurs at 09:00 UTC, so each local day is represented
# by the half-open UTC interval [09:00 UTC on day D, 09:00 UTC on day D+1).
WINDOW_START_UTC_HOUR = 9
# GRIB year used only to pad the trailing UTC-9 local day of the prior year (e.g.
# 2020-12-31 needs 2021-01-01 00/09 UTC). No annual NetCDF is written for this year.
BOUNDARY_PADDING_YEAR = 2021

_INPUT_NAME_SUFFIX = ".grib"


def subset_hour(ds: xr.Dataset, hour: int) -> xr.Dataset:
    """Subset a valid_time-indexed dataset to a specific UTC hour."""
    return ds.where(ds.valid_time.dt.hour == hour, drop=True)


def relabel_to_local_date(ds: xr.Dataset, day_offset: int) -> xr.Dataset:
    """Relabel valid_time to a local_date coordinate with an integer day offset."""
    local_dates = ds.valid_time.values.astype("datetime64[D]") + np.timedelta64(
        day_offset, "D"
    )
    out = ds.assign_coords(local_date=("valid_time", local_dates))
    out = out.swap_dims({"valid_time": "local_date"}).drop_vars("valid_time")
    return out.sortby("local_date")


def first_hour_record(ds: xr.Dataset, hour: int) -> xr.Dataset:
    """Return the first available record for a given UTC hour."""
    hour_ds = subset_hour(ds, hour)
    if hour_ds.sizes.get("valid_time", 0) == 0:
        raise ValueError(f"No valid_time values found for UTC hour {hour}")
    return hour_ds.isel(valid_time=slice(0, 1))


def intersect_dates(*arrays: np.ndarray) -> np.ndarray:
    """Return the sorted intersection of multiple datetime64[D] arrays."""
    if not arrays:
        raise ValueError("At least one date array is required.")
    common = arrays[0]
    for arr in arrays[1:]:
        common = np.intersect1d(common, arr)
    return np.sort(common)


def _target_dates_for_year(year: int) -> np.ndarray:
    """Return contiguous calendar dates for a target year."""
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
    utc_start_times = common_dates + np.timedelta64(WINDOW_START_UTC_HOUR, "h")
    daily = daily.assign_coords(time=("local_date", utc_start_times))
    daily = daily.swap_dims({"local_date": "time"}).sortby("time")
    daily = daily.assign_coords(local_date=("time", common_dates))

    meta = VARIABLE_REGISTRY[varname]
    daily[varname].attrs["long_name"] = meta["long_name"]
    daily[varname].attrs["aggregation_window"] = "09:00 UTC to 09:00 UTC next day"
    daily[varname].attrs[
        "time_coordinate_meaning"
    ] = "UTC start timestamp of the 24-hour UTC-9 daily aggregation window"
    daily[varname].attrs["local_timezone_offset"] = "UTC-9"
    daily.attrs["source"] = "ERA5-Land hourly GRIB"

    if meta["daily_op"] == "sum":
        daily.attrs["processing"] = (
            "daily_total = utc_day_total - cum_00_to_09 + next_00_to_09"
        )
    else:
        daily.attrs["processing"] = (
            "daily_mean = mean(hourly values in UTC-9 window [09:00, 09:00))"
        )

    return daily


def _ensure_valid_time(ds: xr.Dataset) -> xr.Dataset:
    if "valid_time" in ds.dims:
        return ds.sortby("valid_time")
    if "time" in ds.dims:
        return ds.rename({"time": "valid_time"}).sortby("valid_time")
    raise ValueError(f"Expected valid_time or time dimension; dims={list(ds.dims)}")


def compute_daily_utc9_accum_from_hourly(
    current_ds: xr.Dataset, varname: str
) -> xr.Dataset:
    """UTC-9 daily totals for forecast-accumulated variables over an arbitrary span.

    Uses the same reconstruction as the baseline annual workflow, but retains every
    local_date where utc_day_total, cum_00_to_09, and next_00_to_09 are all defined.
    """
    current_ds = _ensure_valid_time(current_ds)
    current_00 = subset_hour(current_ds, 0)
    current_09 = subset_hour(current_ds, WINDOW_START_UTC_HOUR)
    utc_day_total = relabel_to_local_date(current_00, day_offset=-1)
    cum_00_to_09 = relabel_to_local_date(current_09, day_offset=0)
    next_00_to_09 = relabel_to_local_date(current_09, day_offset=-1)

    common_dates = intersect_dates(
        utc_day_total.local_date.values,
        cum_00_to_09.local_date.values,
        next_00_to_09.local_date.values,
    )
    if common_dates.size == 0:
        raise ValueError(f"No complete UTC-9 accumulation days found for {varname!r}.")

    daily = (
        utc_day_total.sel(local_date=common_dates)
        - cum_00_to_09.sel(local_date=common_dates)
        + next_00_to_09.sel(local_date=common_dates)
    )
    return _finalize_daily_dataset(
        varname=varname, daily=daily, common_dates=common_dates
    )


def compute_daily_utc9_mean_from_hourly(merged: xr.Dataset, varname: str) -> xr.Dataset:
    """UTC-9 daily means for state variables; only complete 24-hour windows kept."""
    merged = _ensure_valid_time(merged)
    shifted_dates = (
        merged.valid_time.values - np.timedelta64(WINDOW_START_UTC_HOUR, "h")
    ).astype("datetime64[D]")
    merged = merged.assign_coords(local_date=("valid_time", shifted_dates))

    counts = merged[varname].groupby("local_date").count(dim="valid_time")
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
    daily = merged.groupby("local_date").mean(dim="valid_time")
    common_dates = daily.local_date.values.astype("datetime64[D]")

    if common_dates.size == 0:
        raise ValueError(f"No complete UTC-9 mean days found for {varname!r}.")

    return _finalize_daily_dataset(
        varname=varname, daily=daily, common_dates=common_dates
    )


def compute_daily_utc9_from_hourly(
    hourly_ds: xr.Dataset, registry_key: str
) -> xr.Dataset:
    """Dispatch UTC-9 daily reduction for one variable (pipeline or ad hoc builds)."""
    op = VARIABLE_REGISTRY[registry_key]["daily_op"]
    if op == "sum":
        return compute_daily_utc9_accum_from_hourly(hourly_ds, registry_key)
    if op == "mean":
        return compute_daily_utc9_mean_from_hourly(hourly_ds, registry_key)
    raise ValueError(f"Unknown daily_op {op!r} for {registry_key!r}")


def _year_from_input_filename(name: str, *, prefix: str) -> int:
    if not (name.startswith(prefix) and name.endswith(_INPUT_NAME_SUFFIX)):
        raise ValueError(f"Expected filename like {prefix}1993.grib, got {name!r}")
    year = name[len(prefix) : -len(_INPUT_NAME_SUFFIX)]
    if len(year) != 4 or not year.isdecimal():
        raise ValueError(f"Expected filename like {prefix}1993.grib, got {name!r}")
    return int(year)


def discover_year_files(input_dir: Path, *, varname: str) -> dict[int, Path]:
    """Discover yearly GRIB files for the selected registry variable."""
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    prefix = VARIABLE_REGISTRY[varname]["hourly_prefix"]
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


def _compute_one_year_sum(
    varname: str,
    year: int,
    current_path: Path,
    next_path: Path | None,
) -> xr.Dataset:
    current_ds: xr.Dataset | None = None
    next_ds: xr.Dataset | None = None

    try:
        logging.info("Opening current year: %s", current_path.name)
        current_ds = open_hourly_dataset(current_path, varname=varname)

        current_00 = subset_hour(current_ds, 0)
        current_09 = subset_hour(current_ds, WINDOW_START_UTC_HOUR)

        utc_day_total = relabel_to_local_date(current_00, day_offset=-1)
        cum_00_to_09 = relabel_to_local_date(current_09, day_offset=0)
        next_00_to_09 = relabel_to_local_date(current_09, day_offset=-1)

        if next_path is not None:
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


def _compute_one_year_mean(
    varname: str,
    year: int,
    current_path: Path,
    next_path: Path | None,
) -> xr.Dataset:
    current_ds: xr.Dataset | None = None
    next_ds: xr.Dataset | None = None
    merged: xr.Dataset | None = None

    try:
        logging.info("Opening current year: %s", current_path.name)
        current_ds = open_hourly_dataset(current_path, varname=varname)
        merged = current_ds

        if next_path is not None:
            logging.info("Opening next year for boundary padding: %s", next_path.name)
            next_ds = open_hourly_dataset(next_path, varname=varname)
            next_cutoff = np.datetime64(f"{year + 1}-01-01T09:00:00")
            next_head = next_ds.where(next_ds.valid_time < next_cutoff, drop=True)
            if next_head.sizes.get("valid_time", 0) > 0:
                merged = xr.concat([current_ds, next_head], dim="valid_time").sortby(
                    "valid_time"
                )

        shifted_dates = (
            merged.valid_time.values - np.timedelta64(WINDOW_START_UTC_HOUR, "h")
        ).astype("datetime64[D]")
        merged = merged.assign_coords(local_date=("valid_time", shifted_dates))

        target_dates = _target_dates_for_year(year)
        merged = merged.where(merged.local_date.isin(target_dates), drop=True)
        counts = merged[varname].groupby("local_date").count(dim="valid_time")
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
    """Compute one calendar year of UTC-9 daily values (baseline annual workflow)."""
    if VARIABLE_REGISTRY[varname]["daily_op"] == "sum":
        return _compute_one_year_sum(
            varname=varname,
            year=year,
            current_path=current_path,
            next_path=next_path,
        )
    return _compute_one_year_mean(
        varname=varname,
        year=year,
        current_path=current_path,
        next_path=next_path,
    )
