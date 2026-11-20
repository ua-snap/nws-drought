"""Build the ERA5-Land climatology (1981-2021) from the DestinE Earth Data Hub mirror.

One netCDF file per variable per year, in each variable's climatology directory,
named ``<prefix><YYYY>.nc``. Daily values are rebuilt from the mirror's hourly data
the way the CDS requests produce them (see era5_land_mirror). Small differences
from CDS values are accepted: the mirror stores roughly 12 significant bits.

A year counts as done when its file passes the date-and-variable check and carries
the mirror mark, so running again after a stop continues where it stopped. A
CDS-built yearly file (no mirror mark, or the old GRIB file for tp and pev) is
moved to the archive directory, never deleted, just before its mirror replacement
is written. Years outside the requested range are left alone.
"""

import datetime
import logging
import os
import time
from pathlib import Path

import pandas as pd
import xarray as xr

import era5_land_mirror
from config import BASELINE_DATA_ROOT
from download_helpers import exclusive_download_lock
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, check_output_file

logger = logging.getLogger(__name__)

CLIMATOLOGY_START_YEAR = 1981
CLIMATOLOGY_END_YEAR = 2021
# Only January 1 is kept for the summed variables in the final year: its value is
# the total for December 31 of the year before. The mean variables keep the whole
# final year.
_FINAL_CLIMATOLOGY_YEAR = 2021
CLIMATOLOGY_SUFFIX = ".nc"
ARCHIVE_DIR_NAME = "cds_climatology_archive"
# Global attribute that marks a file built from the mirror; its value is the store.
SOURCE_ATTR = "mirror_source"


class MirrorKeyMissing(RuntimeError):
    """No Earth Data Hub key in the environment."""


class MirrorUnavailable(RuntimeError):
    """The mirror refused the key or could not be reached."""


class ArchiveClash(RuntimeError):
    """A CDS file to archive already has a same-name file in the archive."""


def climatology_file_path(variable_key: str, year: int) -> Path:
    meta = VARIABLE_REGISTRY[variable_key]
    return (
        BASELINE_DATA_ROOT
        / meta["climatology_dir"]
        / f"{meta['prefix']}{year}{CLIMATOLOGY_SUFFIX}"
    )


def staged_path(target: Path) -> Path:
    return target.with_name(f"{target.stem}.partial{target.suffix}")


def _archive_path(path: Path) -> Path:
    return BASELINE_DATA_ROOT / ARCHIVE_DIR_NAME / path.parent.name / path.name


def expected_dates(variable_key: str, year: int) -> list[str]:
    """Valid dates a yearly file holds: every day of the year (for the summed
    variables, January 1 holds the previous year's December 31 total), or only
    January 1 for the summed variables' final year."""
    if (
        VARIABLE_REGISTRY[variable_key]["daily_op"] == "sum"
        and year == _FINAL_CLIMATOLOGY_YEAR
    ):
        return [datetime.date(year, 1, 1).isoformat()]
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    return [day.date().isoformat() for day in days]


def _has_mirror_mark(path: Path) -> bool:
    try:
        with xr.open_dataset(path, engine=NETCDF_ENGINE) as ds:
            return SOURCE_ATTR in ds.attrs
    except Exception:
        return False


def _passes(path: Path, variable_key: str, year: int) -> bool:
    ok, _ = check_output_file(
        path,
        VARIABLE_REGISTRY[variable_key]["short_name"],
        expected_dates(variable_key, year),
    )
    return ok and _has_mirror_mark(path)


def is_mirror_built(variable_key: str, year: int) -> bool:
    return _passes(climatology_file_path(variable_key, year), variable_key, year)


def _cds_built_files(variable_key: str, year: int) -> list[Path]:
    """The year's CDS-built files still in the climatology directory."""
    target = climatology_file_path(variable_key, year)
    cds = target.with_suffix(VARIABLE_REGISTRY[variable_key]["suffix"])
    found = []
    if target.exists() and not _has_mirror_mark(target):
        found.append(target)
    if cds != target and cds.exists():
        found.append(cds)
    return found


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
    hourly = era5_land_mirror.fetch_mirror(store, entry["short_name"], first, last)
    if entry["daily_op"] == "sum":
        daily = era5_land_mirror.daily_totals(hourly, convention)
    else:
        daily = era5_land_mirror.daily_mean_6_hourly(hourly)
    keep = (
        pd.DatetimeIndex(daily.valid_time.values)
        .floor("D")
        .isin(pd.DatetimeIndex(dates))
    )
    daily = daily.isel(valid_time=keep).sortby("latitude", ascending=False)
    daily = daily.rename(entry["short_name"])
    source_attrs = store[entry["short_name"]].attrs
    daily.attrs = {
        k: source_attrs[k] for k in ("units", "long_name") if k in source_attrs
    }
    return daily


def _install_year(daily: xr.DataArray, variable_key: str, year: int) -> Path:
    """Write the year to a staged file, check it, archive the year's CDS files,
    then rename the staged file into place."""
    target = climatology_file_path(variable_key, year)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = staged_path(target)
    name = daily.name
    ds = daily.to_dataset()
    ds.attrs[SOURCE_ATTR] = era5_land_mirror.EDH_STORE_URL
    try:
        ds.to_netcdf(
            staged,
            engine=NETCDF_ENGINE,
            encoding={name: {"dtype": "float32", "zlib": True, "complevel": 4}},
        )
        if not _passes(staged, variable_key, year):
            _, reason = check_output_file(
                staged, name, expected_dates(variable_key, year)
            )
            raise RuntimeError(f"{target}: rebuilt year failed its check ({reason})")
        for cds_file in _cds_built_files(variable_key, year):
            archived = _archive_path(cds_file)
            archived.parent.mkdir(parents=True, exist_ok=True)
            cds_file.rename(archived)
            logger.info("Archived CDS file %s to %s", cds_file, archived)
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

    Raises MirrorKeyMissing or MirrorUnavailable before touching any file when the
    key is missing, refused, or the mirror is unreachable, and ArchiveClash before
    any fetch when a CDS file to archive already has a namesake in the archive.
    """
    api_key = os.getenv(era5_land_mirror.API_KEY_ENV_VAR)
    if not api_key:
        raise MirrorKeyMissing(
            f"Set {era5_land_mirror.API_KEY_ENV_VAR} to an Earth Data Hub API key."
        )
    variable_keys = list(variable_keys or VARIABLE_REGISTRY)
    started = time.perf_counter()
    with exclusive_download_lock(BASELINE_DATA_ROOT / ARCHIVE_DIR_NAME):
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
        for key, years in todo.items():
            for year in years:
                for cds_file in _cds_built_files(key, year):
                    if _archive_path(cds_file).exists():
                        raise ArchiveClash(
                            f"{cds_file.name} is already in "
                            f"{_archive_path(cds_file).parent}; move one of them "
                            "by hand, then run again."
                        )

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
