#!/usr/bin/env python3
"""Compare a cloud copy of ERA5-Land with the CDS yearly files already on disk.

For one sample year over the download bounding box, this script reads the DestinE
Earth Data Hub ERA5-Land Zarr store, rebuilds the daily values the way the CDS
requests produce them, and compares them value by value with the CDS yearly files.
It makes no CDS requests. The result is a markdown report.

Daily values are rebuilt as CDS builds them:
  - summed variables (tp, pev): the 00:00 UTC value of day D+1 is the total for
    day D. If the store holds hourly increments instead of running totals, the 24
    increments ending at 00:00 of day D+1 are summed.
  - mean variables (swe, swvl1, swvl2): the mean of the 00, 06, 12 and 18 UTC values.

The API key is read from the environment variable named by API_KEY_ENV_VAR. Without
it, the report records that the candidate could not be tested and nothing is fetched.
A mirror should replace CDS only if every value matches exactly.

Needs the optional `mirror` dependency group for remote access:
    uv run --group mirror python -m baseline_data_generation_scripts.compare_era5_land_mirror
"""

import argparse
import datetime
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config import BASELINE_DATA_ROOT, DL_BBOX
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import ds_combination, setup_logging

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "EDH_API_KEY"
EDH_STORE_URL = "https://data.earthdatahub.destine.eu/era5/era5-land-v0.zarr"
DEFAULT_REPORT = Path(__file__).resolve().parent / "mirror_comparison.md"
MEAN_HOURS = (0, 6, 12, 18)
# share of varying pixel-days whose magnitude never falls within the accumulation
# period; above this the store is taken to hold running totals
_ACCUMULATED_MONOTONIC_SHARE = 0.9

UNTESTED_CANDIDATES = """\
## Candidates not tested

- **ECMWF ARCO Zarr store (CDS, beta).** It does not include potential evaporation,
  so it cannot supply every variable the indices need. Its accumulations are also
  de-accumulated and the data are repackaged (renamed time coordinate, longitudes
  in -180..180, undocumented precision), and ECMWF says access is beta and rate-capped.
- **Google Earth Engine (ECMWF/ERA5_LAND/DAILY_AGGR).** Its daily means are 24-hour
  means over every hour, not the 00/06/12/18 UTC samples CDS uses, so the mean variables
  cannot match. It is also not a Zarr store: data come out through the Earth Engine
  API or exports, which needs an Earth Engine account and a Cloud project.
- **Google ARCO-ERA5, AWS open data (Earthmover, Planet OS) and Microsoft Planetary
  Computer.** These hold plain ERA5 at 0.25 degrees, not ERA5-Land at 0.1 degrees.
  No ERA5-Land copy was found in them.
"""


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
# Comparison and report (pure functions)
# ---------------------------------------------------------------------------


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
    lon = ((da.longitude + 180) % 360) - 180
    return (
        da.assign_coords(
            longitude=np.round(lon.values, 4), latitude=np.round(da.latitude.values, 4)
        )
        .sortby("longitude")
        .sortby("latitude")
    )


def compare_values(candidate: xr.DataArray, cds: xr.DataArray) -> dict:
    """Value-by-value differences between a rebuilt candidate and the CDS values.

    Exact match requires every CDS point to be present in the candidate, the same
    missing-value pattern, and identical values.
    """
    candidate, cds = normalize(candidate), normalize(cds)
    cand_aligned, cds_aligned = xr.align(candidate, cds, join="inner")
    c = np.asarray(cand_aligned.values, dtype="float64")
    d = np.asarray(cds_aligned.values, dtype="float64")
    c_ok, d_ok = np.isfinite(c), np.isfinite(d)
    both = c_ok & d_ok
    diffs = np.abs(c[both] - d[both])
    n = int(diffs.size)
    stats = {
        "points_compared": n,
        "cds_points_unmatched": int(cds.size - cds_aligned.size),
        "missing_mismatch": int(np.sum(c_ok != d_ok)),
        "max_abs_diff": float(diffs.max()) if n else float("nan"),
        "median_abs_diff": float(np.median(diffs)) if n else float("nan"),
        "share_equal": float(np.mean(diffs == 0)) if n else float("nan"),
    }
    stats["exact_match"] = bool(
        n > 0
        and stats["max_abs_diff"] == 0
        and stats["missing_mismatch"] == 0
        and stats["cds_points_unmatched"] == 0
    )
    return stats


def render_variable_row(var: str, stats: dict) -> str:
    verdict = "exact match" if stats["exact_match"] else "not an exact match"
    return (
        f"| {var} | {stats.get('rebuild', '')} | {stats['points_compared']} "
        f"| {stats['cds_points_unmatched']} | {stats['missing_mismatch']} "
        f"| {stats['max_abs_diff']:.6g} | {stats['median_abs_diff']:.6g} "
        f"| {stats['share_equal']:.4%} | {verdict} |"
    )


def render_report(
    *,
    year: int,
    tested: bool,
    results: dict | None = None,
    skipped: dict | None = None,
    fetch_seconds: float | None = None,
    cds_request_seconds: float | None = None,
) -> str:
    results = results or {}
    skipped = skipped or {}
    lines = [
        "# ERA5-Land cloud mirror comparison",
        "",
        f"Generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC "
        f"by `compare_era5_land_mirror.py`. Sample year: {year}. "
        f"Bounding box (N, W, S, E): {DL_BBOX}.",
        "",
        "Daily values are rebuilt the way the CDS requests produce them: the 00:00 UTC "
        "value of the next day for tp and pev (or the sum of the day's 24 hourly "
        "increments if the store is de-accumulated), and the mean of the 00, 06, 12 "
        "and 18 UTC values for swe, swvl1 and swvl2. They are compared with the CDS "
        "yearly files on disk. A mirror replaces CDS only if every value matches exactly.",
        "",
        "## DestinE Earth Data Hub (ERA5-Land Zarr)",
        "",
        f"Store: `{EDH_STORE_URL}`",
        "",
    ]
    if not tested:
        lines += [
            f"**Result: not tested.** No API key was found in the `{API_KEY_ENV_VAR}` "
            "environment variable, so the store was not opened. Create a free Earth "
            f"Data Hub account, set `{API_KEY_ENV_VAR}`, install the `mirror` "
            "dependency group and rerun. CDS stays the source.",
            "",
        ]
    else:
        lines += [
            "| Variable | Daily rebuild | Points compared | CDS points missing "
            "from mirror | Missing-value mismatches | Max abs diff | Median abs diff "
            "| Share exactly equal | Result |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        lines += [render_variable_row(v, s) for v, s in results.items()]
        lines.append("")
        for var, reason in skipped.items():
            lines.append(f"- {var}: not compared ({reason}).")
        if skipped:
            lines.append("")
        all_exact = (
            bool(results)
            and not skipped
            and all(s["exact_match"] for s in results.values())
        )
        lines.append(
            "**Verdict:** every value matches exactly; the mirror can be considered "
            "for the climatology download."
            if all_exact
            else "**Verdict:** not an exact match for every variable; the "
            "climatology keeps downloading from CDS."
        )
        lines.append("")
        lines.append("### Fetch time")
        lines.append("")
        if fetch_seconds is not None:
            lines.append(
                f"- Mirror fetch for the sample year: {fetch_seconds:.1f} s "
                "(all compared variables, hourly data)."
            )
        if cds_request_seconds is not None:
            lines.append(
                f"- CDS request time for the same year: {cds_request_seconds:.1f} s."
            )
            if fetch_seconds:
                lines.append(
                    f"- Ratio CDS / mirror: {cds_request_seconds / fetch_seconds:.1f}x."
                )
        else:
            lines.append(
                "- CDS request time not supplied (pass `--cds-request-seconds`)."
            )
        lines.append("")
    lines.append(UNTESTED_CANDIDATES)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O
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


def fetch_mirror_year(store: xr.Dataset, short_name: str, year: int) -> xr.DataArray:
    """Load the hourly values for one year over the bounding box, starting at 00:00 on
    31 Dec of the previous year so the first day's total can be rebuilt."""
    north, west, south, east = DL_BBOX
    da = store[short_name]
    time_dim = "valid_time" if "valid_time" in da.dims else "time"
    da = da.sel({time_dim: slice(f"{year - 1}-12-31T00:00", f"{year}-12-31T23:00")})
    lat = da.latitude.values
    lat_slice = slice(north, south) if lat[0] > lat[-1] else slice(south, north)
    if float(da.longitude.max()) > 180:
        west, east = west % 360, east % 360
    return normalize(da.sel(latitude=lat_slice, longitude=slice(west, east)).load())


def cds_year_file(var: str, year: int) -> Path:
    entry = VARIABLE_REGISTRY[var]
    return BASELINE_DATA_ROOT.joinpath(
        entry["climatology_dir"], f"{entry['prefix']}{year}{entry['suffix']}"
    )


def load_cds_year(var: str, year: int) -> xr.DataArray:
    entry = VARIABLE_REGISTRY[var]
    ds = ds_combination([cds_year_file(var, year)], entry["suffix"])
    return ds[entry["short_name"]].load()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--year", type=int, default=2000, help="Sample year to compare."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Markdown report path.",
    )
    parser.add_argument(
        "--cds-request-seconds",
        type=float,
        default=None,
        help="Time CDS took to deliver the same year, for the speed comparison.",
    )
    parser.add_argument(
        "--accumulation",
        choices=("auto", "accumulated", "increments"),
        default="auto",
        help=(
            "How the store holds tp and pev: running totals since 00 UTC, hourly "
            "increments, or detect from the data (default)."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    setup_logging()
    args = parse_args(argv)
    api_key = os.getenv(API_KEY_ENV_VAR)

    if not api_key:
        logger.warning("%s is not set; writing a 'not tested' report", API_KEY_ENV_VAR)
        args.report.write_text(render_report(year=args.year, tested=False))
        return

    store = open_mirror_store(api_key)
    results, skipped = {}, {}
    fetch_seconds = 0.0
    for var, entry in VARIABLE_REGISTRY.items():
        path = cds_year_file(var, args.year)
        if not path.exists():
            skipped[var] = f"CDS file not found: {path}"
            continue
        logger.info("Fetching %s for %s from the mirror", var, args.year)
        start = time.perf_counter()
        hourly = fetch_mirror_year(store, entry["short_name"], args.year)
        fetch_seconds += time.perf_counter() - start

        if entry["daily_op"] == "sum":
            convention = args.accumulation
            if convention == "auto":
                convention = detect_accumulation_convention(hourly)
            daily = daily_totals(hourly, convention)
            rebuild = f"00:00 next day ({convention})"
        else:
            daily = daily_mean_6_hourly(hourly)
            rebuild = "mean of 00/06/12/18 UTC"

        stats = compare_values(daily, load_cds_year(var, args.year))
        stats["rebuild"] = rebuild
        results[var] = stats
        logger.info("%s: %s", var, stats)

    args.report.write_text(
        render_report(
            year=args.year,
            tested=True,
            results=results,
            skipped=skipped,
            fetch_seconds=fetch_seconds if results else None,
            cds_request_seconds=args.cds_request_seconds,
        )
    )
    logger.info("Report written to %s", args.report)


if __name__ == "__main__":
    main()
