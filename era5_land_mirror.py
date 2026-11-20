"""Read ERA5-Land from the DestinE Earth Data Hub Zarr mirror and rebuild daily
values the way the CDS requests produce them.

Daily values:
  - summed variables (tp, pev): the 00:00 UTC value of day D+1 is the total for
    day D. If the store holds hourly increments instead of running totals, the 24
    increments ending at 00:00 of day D+1 are summed. Which form the store uses is
    detected from tp and applied to pev too.
  - mean variables (swe, swvl1, swvl2): the mean of the 00, 06, 12 and 18 UTC values.

Opening the store needs the optional `mirror` dependency group (zarr, aiohttp);
importing this module does not.
"""

import datetime
import logging

import numpy as np
import pandas as pd
import xarray as xr

from config import DL_BBOX
from era5_land_variable_registry import VARIABLE_REGISTRY

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "EDH_API_KEY"
EDH_STORE_URL = "https://data.earthdatahub.destine.eu/era5/era5-land-v0.zarr"
MEAN_HOURS = (0, 6, 12, 18)
# share of varying pixel-days whose magnitude never falls within the accumulation
# period; above this the store is taken to hold running totals
_ACCUMULATED_MONOTONIC_SHARE = 0.9
# Most storage blocks downloaded from the store at the same time. A fixed number
# keeps the load on the mirror the same whatever node the job runs on.
MAX_CONCURRENT_FETCHES = 4


# ---------------------------------------------------------------------------
# Daily rebuilds (pure functions on hourly DataArrays with a valid_time dimension)
# ---------------------------------------------------------------------------


def _accumulation_period(times) -> pd.DatetimeIndex:
    """Day whose total each hourly value belongs to: 01:00 on D through 00:00 on D+1."""
    return (pd.DatetimeIndex(times) - pd.Timedelta(hours=1)).floor("D")


def daily_totals_from_accumulated(hourly: xr.DataArray) -> xr.DataArray:
    """Daily totals from running totals since 00 UTC: the 00:00 values, labeled as CDS
    labels them (the total for day D sits at 00:00 on D+1)."""
    return hourly.sel(valid_time=hourly.valid_time.dt.hour == 0)


def daily_totals_from_increments(hourly: xr.DataArray) -> xr.DataArray:
    """Daily totals from hourly increments: the sum of the 24 increments from 01:00 on
    D through 00:00 on D+1, labeled at 00:00 on D+1. Incomplete days are dropped."""
    period = _accumulation_period(hourly.valid_time.values)
    counts = pd.Series(period).value_counts()
    complete = counts[counts == 24].index
    totals = (
        hourly.assign_coords(period=("valid_time", period))
        .groupby("period")
        .sum("valid_time", skipna=False)
    )
    totals = totals.sel(period=totals.period.isin(complete.values))
    labels = pd.DatetimeIndex(totals.period.values) + pd.Timedelta(days=1)
    return (
        totals.rename(period="valid_time")
        .assign_coords(valid_time=labels)
        .sortby("valid_time")
    )


def detect_accumulation_convention(hourly: xr.DataArray) -> str:
    """Return "accumulated" if values are running totals since 00 UTC, else "increments".

    Running totals never shrink in magnitude within an accumulation period (01:00 on D
    through 00:00 on D+1); hourly increments almost always do somewhere in the day.
    Only complete periods with values that vary are counted.
    """
    period = _accumulation_period(hourly.valid_time.values)
    counts = pd.Series(period).value_counts()
    monotonic = 0
    varying = 0
    for day in counts[counts == 24].index:
        block = np.abs(np.asarray(hourly.values)[period == day]).astype("float64")
        block = block.reshape(24, -1)
        finite = np.all(np.isfinite(block), axis=0)
        block = block[:, finite]
        varies = np.ptp(block, axis=0) > 0
        block = block[:, varies]
        if block.size == 0:
            continue
        tol = 1e-6 * block.max(axis=0)
        monotonic += int(np.sum(np.all(np.diff(block, axis=0) >= -tol, axis=0)))
        varying += block.shape[1]
    if varying == 0:
        raise ValueError("No complete, varying days to detect the convention from")
    share = monotonic / varying
    return "accumulated" if share >= _ACCUMULATED_MONOTONIC_SHARE else "increments"


def daily_totals(hourly: xr.DataArray, convention: str) -> xr.DataArray:
    if convention == "accumulated":
        return daily_totals_from_accumulated(hourly)
    if convention == "increments":
        return daily_totals_from_increments(hourly)
    raise ValueError(f"Unknown accumulation convention: {convention!r}")


def daily_mean_6_hourly(hourly: xr.DataArray) -> xr.DataArray:
    """Mean of the 00, 06, 12 and 18 UTC values of each day, labeled at 00:00 on that
    day. Days missing any of the four samples are dropped."""
    samples = hourly.sel(valid_time=hourly.valid_time.dt.hour.isin(MEAN_HOURS))
    day = pd.DatetimeIndex(samples.valid_time.values).floor("D")
    counts = pd.Series(day).value_counts()
    complete = counts[counts == len(MEAN_HOURS)].index
    means = (
        samples.assign_coords(day=("valid_time", day))
        .groupby("day")
        .mean("valid_time", skipna=False)
    )
    means = means.sel(day=means.day.isin(complete.values))
    return means.rename(day="valid_time").sortby("valid_time")


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


def wrap_longitudes(longitudes) -> np.ndarray:
    """Longitudes in -180..180, rounded to 4 decimals. Rounding comes first, so the
    dateline column stored a hair below 180 (179.99998 in a 0..360 store) becomes
    -180 like the CDS column, instead of staying at +180."""
    lon = np.round(np.asarray(longitudes, dtype="float64"), 4)
    return np.round(((lon + 180) % 360) - 180, 4)


def normalize(da: xr.DataArray) -> xr.DataArray:
    """Common dimension names, longitudes in -180..180, rounded grid coordinates and
    no auxiliary coordinates, so the two sources align on value."""
    renames = {
        old: new
        for old, new in (
            ("time", "valid_time"),
            ("lat", "latitude"),
            ("lon", "longitude"),
        )
        if old in da.dims
    }
    da = da.rename(renames)
    da = da.drop_vars([c for c in da.coords if c not in da.dims])
    return (
        da.assign_coords(
            longitude=wrap_longitudes(da.longitude.values),
            latitude=np.round(da.latitude.values, 4),
        )
        .sortby("longitude")
        .sortby("latitude")
    )


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------


def open_mirror_store(api_key: str) -> xr.Dataset:
    """Open the Earth Data Hub Zarr store lazily. The key goes in an HTTP basic-auth
    header rather than the URL, so it does not appear in error messages."""
    import aiohttp
    import zarr  # noqa: F401  (fails early with a clear message if not installed)

    return xr.open_dataset(
        EDH_STORE_URL,
        engine="zarr",
        chunks={},
        storage_options={"client_kwargs": {"auth": aiohttp.BasicAuth("edh", api_key)}},
    )


def fetch_mirror(
    store: xr.Dataset, short_name: str, start: datetime.date, end: datetime.date
) -> xr.DataArray:
    """Load the hourly values from ``start`` through ``end`` over the bounding box,
    starting at 00:00 on the day before ``start`` so the first day's total can be
    rebuilt."""
    da = store[short_name]
    time_dim = "valid_time" if "valid_time" in da.dims else "time"
    first = start - datetime.timedelta(days=1)
    da = da.sel({time_dim: slice(f"{first}T00:00", f"{end}T23:00")})
    lat_idx, lon_idx = bbox_indices(da.latitude.values, da.longitude.values)
    da = da.isel(latitude=lat_idx, longitude=lon_idx)
    return normalize(da.load(scheduler="threads", num_workers=MAX_CONCURRENT_FETCHES))


# Half of the 0.1 degree ERA5-Land grid spacing: grid points this close outside the
# bounding box are kept, so an edge stored as 72.0000001 is not dropped.
_EDGE_TOLERANCE = 0.05


def bbox_indices(latitudes, longitudes) -> tuple[np.ndarray, np.ndarray]:
    """Indices of the grid rows and columns inside the download bounding box,
    edges included within half a grid cell. Longitudes are compared in -180..180,
    so a store in 0..360 or one holding +180 rather than -180 gives the same
    columns."""
    north, west, south, east = DL_BBOX
    lat = np.asarray(latitudes, dtype="float64")
    lon = wrap_longitudes(longitudes)
    lat_idx = np.flatnonzero(
        (lat >= south - _EDGE_TOLERANCE) & (lat <= north + _EDGE_TOLERANCE)
    )
    lon_idx = np.flatnonzero(
        (lon >= west - _EDGE_TOLERANCE) & (lon <= east + _EDGE_TOLERANCE)
    )
    return lat_idx, lon_idx


# Days of precipitation read to tell how the store holds its summed variables.
_CONVENTION_SAMPLE_DAYS = 7


def store_accumulation_convention(store: xr.Dataset, start: datetime.date) -> str:
    """How the store holds its summed variables, detected from precipitation.

    One store uses one form for every summed variable, so it is read from tp, whose
    running totals never shrink within a day. Potential evaporation cannot be used:
    its running totals shrink whenever the flux changes sign (dew or frost
    deposition), which looks like hourly increments.
    """
    end = start + datetime.timedelta(days=_CONVENTION_SAMPLE_DAYS - 1)
    sample = fetch_mirror(store, VARIABLE_REGISTRY["tp"]["short_name"], start, end)
    convention = detect_accumulation_convention(sample)
    logger.info(
        "The store holds summed variables as %s (detected from tp, %s to %s)",
        convention,
        start,
        end,
    )
    return convention
