"""Build the ERA5-Land climatology (1981-2020) from the DestinE Earth Data Hub mirror.

One netCDF file per variable per year, in each variable's climatology directory,
named ``<prefix><YYYY>.nc``. Daily values are rebuilt from the mirror's hourly data
the way the CDS requests produce them (see era5_land_mirror), and every daily value
is labeled by the day it measures: a precipitation or evaporation total for day D
is the 00:00 reading on D+1, so the 2020 files read 1 January 2021. Small
differences from CDS values are accepted: the mirror stores roughly 12 significant
bits.

A year counts as done when its file passes the date-and-variable check, so running
again after a stop continues where it stopped.
"""

import datetime
import functools
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import era5_land_mirror
from config import BASELINE_DATA_ROOT
from download_helpers import exclusive_download_lock
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, check_output_file

logger = logging.getLogger(__name__)

CLIMATOLOGY_START_YEAR = 1981
CLIMATOLOGY_END_YEAR = 2020
CLIMATOLOGY_SUFFIX = ".nc"


_CDS_GRID_FILE = Path(__file__).resolve().parent / "era5_land_cds_grid.json"
# Mirror coordinates rounded to 4 decimals sit within float noise of the CDS values
_GRID_TOLERANCE = 1e-6


@functools.cache
def cds_grid() -> dict[str, list[float]]:
    """Latitudes and longitudes over the download box exactly as the CDS
    downloads store them (for example 71.80000000000001)."""
    return json.loads(_CDS_GRID_FILE.read_text())


def _on_cds_grid(daily: xr.DataArray) -> xr.DataArray:
    """Replace the rounded mirror coordinates with the CDS floats, so the
    climatology aligns exactly with the recurring CDS files."""
    grid = cds_grid()
    exact = {}
    for dim in ("latitude", "longitude"):
        values = daily[dim].values
        cds = np.asarray(grid[dim])
        gap = np.abs(values[:, None] - cds[None, :])
        nearest = gap.argmin(axis=1)
        off = gap[np.arange(values.size), nearest] > _GRID_TOLERANCE
        if off.any():
            raise RuntimeError(
                f"Mirror {dim} values {values[off][:3].tolist()} are not on the "
                "CDS grid"
            )
        exact[dim] = cds[nearest]
    return daily.assign_coords(exact)


class MirrorKeyMissing(RuntimeError):
    """No Earth Data Hub key in the environment."""


class MirrorUnavailable(RuntimeError):
    """The mirror refused the key or could not be reached."""


def climatology_file_path(variable_key: str, year: int) -> Path:
    meta = VARIABLE_REGISTRY[variable_key]
    return (
        BASELINE_DATA_ROOT
        / meta["climatology_dir"]
        / f"{meta['prefix']}{year}{CLIMATOLOGY_SUFFIX}"
    )


def staged_path(target: Path) -> Path:
    # not "*.nc", so a file left by a killed run is never taken for a year
    return target.with_name(f"{target.name}.partial")


def expected_dates(variable_key: str, year: int) -> list[str]:
    """Every day of the year, each labeled by the day it measures."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    return [day.date().isoformat() for day in days]


def check_year_file(path: Path, variable_key: str, year: int) -> tuple[bool, str]:
    """Whether ``path`` holds the variable for every day of ``year``, and why not."""
    return check_output_file(
        path,
        VARIABLE_REGISTRY[variable_key]["short_name"],
        expected_dates(variable_key, year),
    )


def is_mirror_built(variable_key: str, year: int) -> bool:
    return check_year_file(
        climatology_file_path(variable_key, year), variable_key, year
    )[0]


def _open_checked_store(api_key: str) -> xr.Dataset:
    """Open the store and read one value, so a refused key or an unreachable
    mirror stops the run before any file is moved or written."""
    try:
        store = era5_land_mirror.open_mirror_store(api_key)
        tp = store[VARIABLE_REGISTRY["tp"]["short_name"]]
        tp.isel({dim: 0 for dim in tp.dims}).values
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status in (401, 403) or " 401" in f" {exc}" or " 403" in f" {exc}":
            raise MirrorUnavailable(
                f"The Earth Data Hub mirror rejected the key in "
                f"{era5_land_mirror.API_KEY_ENV_VAR} ({type(exc).__name__})."
            ) from None
        raise MirrorUnavailable(
            f"The Earth Data Hub mirror could not be reached: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return store


def _daily_year(store, variable_key: str, year: int, convention: str | None):
    """The year's daily values, north to south, trimmed to the expected dates."""
    entry = VARIABLE_REGISTRY[variable_key]
    dates = expected_dates(variable_key, year)
    first, last = (datetime.date.fromisoformat(d) for d in (dates[0], dates[-1]))
    if entry["daily_op"] == "sum":
        # the total for the year's last day is the 00:00 reading the next day
        last += datetime.timedelta(days=1)
    hourly = era5_land_mirror.fetch_mirror(store, entry["short_name"], first, last)
    if entry["daily_op"] == "sum":
        # rebuilt totals sit at 00:00 on the day after the one they measure
        daily = era5_land_mirror.daily_totals(hourly, convention)
        daily = daily.assign_coords(
            valid_time=daily.valid_time - np.timedelta64(1, "D")
        )
    else:
        daily = era5_land_mirror.daily_mean_6_hourly(hourly)
    keep = (
        pd.DatetimeIndex(daily.valid_time.values)
        .floor("D")
        .isin(pd.DatetimeIndex(dates))
    )
    daily = _on_cds_grid(
        daily.isel(valid_time=keep).sortby("latitude", ascending=False)
    )
    daily = daily.rename(entry["short_name"])
    source_attrs = store[entry["short_name"]].attrs
    daily.attrs = {
        k: source_attrs[k] for k in ("units", "long_name") if k in source_attrs
    }
    return daily


def _install_year(daily: xr.DataArray, variable_key: str, year: int) -> Path:
    """Write the year to a staged file, check it, then rename it into place."""
    target = climatology_file_path(variable_key, year)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = staged_path(target)
    name = daily.name
    ds = daily.to_dataset()
    ds.attrs["source"] = f"ERA5-Land from {era5_land_mirror.EDH_STORE_URL}"
    try:
        ds.to_netcdf(
            staged,
            engine=NETCDF_ENGINE,
            encoding={name: {"dtype": "float32", "zlib": True, "complevel": 4}},
        )
        ok, reason = check_year_file(staged, variable_key, year)
        if not ok:
            raise RuntimeError(f"{target}: rebuilt year failed its check ({reason})")
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return target


def download_era5_land_climatology(
    variable_keys=None,
    start_year: int = CLIMATOLOGY_START_YEAR,
    end_year: int = CLIMATOLOGY_END_YEAR,
) -> None:
    """Build the yearly climatology files for ``variable_keys`` (default: every
    variable) over ``start_year``..``end_year`` from the Earth Data Hub mirror.

    Raises MirrorKeyMissing or MirrorUnavailable before writing any file when the
    key is missing, refused, or the mirror is unreachable.
    """
    api_key = os.getenv(era5_land_mirror.API_KEY_ENV_VAR)
    if not api_key:
        raise MirrorKeyMissing(
            f"Set {era5_land_mirror.API_KEY_ENV_VAR} to an Earth Data Hub API key."
        )
    variable_keys = list(variable_keys or VARIABLE_REGISTRY)
    started = time.perf_counter()
    with exclusive_download_lock(BASELINE_DATA_ROOT):
        store = _open_checked_store(api_key)
        logger.info(
            "Climatology download %d-%d from %s for %s, at most %d storage blocks "
            "at a time",
            start_year,
            end_year,
            era5_land_mirror.EDH_STORE_URL,
            ", ".join(variable_keys),
            era5_land_mirror.MAX_CONCURRENT_FETCHES,
        )
        todo = {
            key: [
                year
                for year in range(start_year, end_year + 1)
                if not is_mirror_built(key, year)
            ]
            for key in variable_keys
        }
        summed_years = [
            year
            for key, years in todo.items()
            if VARIABLE_REGISTRY[key]["daily_op"] == "sum"
            for year in years
        ]
        convention = None
        if summed_years:
            convention = era5_land_mirror.store_accumulation_convention(
                store, datetime.date(min(summed_years), 1, 1)
            )

        for key, years in todo.items():
            for year in years:
                year_started = time.perf_counter()
                daily = _daily_year(store, key, year, convention)
                path = _install_year(daily, key, year)
                logger.info(
                    "%s %d: built %s in %.1f s (%.0f s elapsed)",
                    key,
                    year,
                    path.name,
                    time.perf_counter() - year_started,
                    time.perf_counter() - started,
                )
    logger.info(
        "Climatology download finished in %.0f s", time.perf_counter() - started
    )
