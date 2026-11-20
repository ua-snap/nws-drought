#!/usr/bin/env python3
"""Compare a cloud copy of ERA5-Land with CDS, by value and by download time.

For a sample period over the download bounding box (a whole year by default, or
some of its months with --months), this script reads the DestinE Earth Data Hub
ERA5-Land Zarr store, rebuilds the daily values the way the CDS requests produce
them, and compares them value by value with the CDS values. The CDS values come
from the climatology yearly files on disk, which makes no CDS request, or, with
--from-cds, from a fresh CDS request for the same variable and months, timed so
the report can set the CDS wall time beside the mirror's. --variable limits the
run to some variables. The result is a markdown report.

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

A small timed test, one variable over three months:
    uv run --frozen --group mirror python -m baseline_data_generation_scripts.compare_era5_land_mirror \
        --year 2000 --months 1-3 --variable swvl1 --from-cds
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

from cds_requests import run_request
from config import BASELINE_DATA_ROOT, DL_BBOX
from download_helpers import (
    _ALL_DAYS,
    build_cds_request,
    bundle_suffix,
    climatology_file_path,
    exclusive_download_lock,
    group_variables_by_dataset,
    month_dates,
    split_then_install,
)
from file_helpers import check_output_file
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import ds_combination, setup_logging

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "EDH_API_KEY"
EDH_STORE_URL = "https://data.earthdatahub.destine.eu/era5/era5-land-v0.zarr"
DEFAULT_REPORT = Path(__file__).resolve().parent / "mirror_comparison.md"
DEFAULT_CDS_DIR = BASELINE_DATA_ROOT / "mirror_comparison"
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


def _unmatched(full: xr.DataArray, aligned: xr.DataArray) -> list:
    values = np.setdiff1d(full.values, aligned.values)
    if np.issubdtype(values.dtype, np.floating):
        return [float(v) for v in values]
    return [str(v) for v in values]


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
        # CDS grid rows, columns and days with no counterpart in the candidate
        "cds_latitudes_unmatched": _unmatched(cds.latitude, cds_aligned.latitude),
        "cds_longitudes_unmatched": _unmatched(cds.longitude, cds_aligned.longitude),
        "cds_days_unmatched": len(_unmatched(cds.valid_time, cds_aligned.valid_time)),
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


def _list_cell(values: list, limit: int = 6) -> str:
    if not values:
        return "none"
    shown = ", ".join(f"{v:g}" if isinstance(v, float) else v for v in values[:limit])
    more = f" and {len(values) - limit} more" if len(values) > limit else ""
    return f"{len(values)} ({shown}{more})"


def render_grid_alignment(results: dict) -> list[str]:
    """Which CDS grid rows, columns and days the mirror has no counterpart for."""
    lines = [
        "### Grid alignment",
        "",
        "CDS latitudes, longitudes and days with no matching mirror point after "
        "longitudes are put in -180..180 and coordinates rounded to 4 decimals. "
        "\"none\" in every column means the two grids line up point for point.",
        "",
        "| Variable | CDS latitudes unmatched | CDS longitudes unmatched "
        "| CDS days unmatched |",
        "|---|---|---|---|",
    ]
    for var, stats in results.items():
        lines.append(
            f"| {var} | {_list_cell(stats.get('cds_latitudes_unmatched', []))} "
            f"| {_list_cell(stats.get('cds_longitudes_unmatched', []))} "
            f"| {stats.get('cds_days_unmatched', 0)} |"
        )
    lines.append("")
    return lines


def render_report(
    *,
    period: str,
    tested: bool,
    results: dict | None = None,
    skipped: dict | None = None,
    fetch_seconds: float | None = None,
    cds_request_seconds: float | None = None,
    timings: dict | None = None,
) -> str:
    """Markdown report. ``timings`` is {variable: (mirror seconds, CDS seconds or
    None)} for a run that timed a fresh CDS request per variable."""
    results = results or {}
    skipped = skipped or {}
    lines = [
        "# ERA5-Land cloud mirror comparison",
        "",
        f"Generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC "
        f"by `compare_era5_land_mirror.py`. Sample period: {period}. "
        f"Bounding box (N, W, S, E): {DL_BBOX}.",
        "",
        "Daily values are rebuilt the way the CDS requests produce them: the 00:00 UTC "
        "value of the next day for tp and pev (or the sum of the day's 24 hourly "
        "increments if the store is de-accumulated), and the mean of the 00, 06, 12 "
        "and 18 UTC values for swe, swvl1 and swvl2. They are compared with the CDS "
        "values for the same period. A mirror replaces CDS only if every value "
        "matches exactly.",
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
        lines += render_grid_alignment(results)
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
        if timings:
            lines += [
                "| Variable | Mirror fetch (hourly data) | CDS request, wall time "
                "(queue + run + transfer) | CDS / mirror |",
                "|---|---|---|---|",
            ]
            for var, (mirror_s, cds_s) in timings.items():
                cds_cell = "not timed (file already on disk)"
                ratio = ""
                if cds_s is not None:
                    cds_cell = f"{cds_s:.1f} s"
                    ratio = f"{cds_s / mirror_s:.1f}x" if mirror_s else ""
                lines.append(f"| {var} | {mirror_s:.1f} s | {cds_cell} | {ratio} |")
            lines.append("")
            lines.append(
                "The CDS request log in the run's output splits each CDS time into "
                "queue, run and transfer, and flags requests served from the CDS cache."
            )
        if fetch_seconds is not None:
            lines.append(
                f"- Mirror fetch for the sample period: {fetch_seconds:.1f} s "
                "(all compared variables, hourly data)."
            )
        if cds_request_seconds is not None:
            lines.append(
                f"- CDS request time for the same period: {cds_request_seconds:.1f} s."
            )
            if fetch_seconds:
                lines.append(
                    f"- Ratio CDS / mirror: {cds_request_seconds / fetch_seconds:.1f}x."
                )
        elif not timings:
            lines.append(
                "- CDS request time not supplied (pass `--cds-request-seconds`, "
                "or `--from-cds` to time a fresh request)."
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


def period_bounds(year: int, months: tuple[int, int]) -> tuple[datetime.date, datetime.date]:
    """First and last day of the months ``months[0]`` through ``months[1]`` of ``year``."""
    first, last = months
    end = datetime.date(year, last, 1) + datetime.timedelta(days=32)
    return datetime.date(year, first, 1), end.replace(day=1) - datetime.timedelta(days=1)


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
    return normalize(da.isel(latitude=lat_idx, longitude=lon_idx).load())


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


def load_cds(path: Path, var: str, start: datetime.date, end: datetime.date):
    """The CDS daily values in ``path`` from ``start`` through ``end``."""
    entry = VARIABLE_REGISTRY[var]
    da = ds_combination([path], entry["suffix"])[entry["short_name"]]
    return da.sel(valid_time=slice(str(start), f"{end}T23:00")).load()


def expected_cds_dates(start: datetime.date, end: datetime.date) -> list[str]:
    """Valid dates a CDS file for whole months ``start`` through ``end`` holds."""
    return [
        date
        for month in range(start.month, end.month + 1)
        for date in month_dates(start.year, month)
    ]


def cds_file_path(cds_dir: Path, var: str, start, end) -> Path:
    entry = VARIABLE_REGISTRY[var]
    return (
        Path(cds_dir)
        / f"{entry['prefix']}{start:%Y-%m}_to_{end:%Y-%m}{entry['suffix']}"
    )


def fetch_cds(
    var: str, start: datetime.date, end: datetime.date, cds_dir: Path, *, client=None
) -> tuple[Path, float | None]:
    """Request ``var`` for the whole months ``start`` through ``end`` from CDS, one
    request, into ``cds_dir``. Returns the installed file and the request's wall
    time, or None for the time when a file that passes the output check is
    already there (nothing is requested)."""
    entry = VARIABLE_REGISTRY[var]
    target = cds_file_path(cds_dir, var, start, end)
    expected = expected_cds_dates(start, end)
    if target.exists() and check_output_file(target, entry["short_name"], expected)[0]:
        logger.info("Reusing %s; the CDS time is not measured", target)
        return target, None
    (dataset,) = group_variables_by_dataset([var])
    months = [f"{m:02d}" for m in range(start.month, end.month + 1)]
    request = build_cds_request(dataset, (var,), start.year, months, _ALL_DAYS)
    bundle = target.with_name(f"{target.stem}_download{bundle_suffix(dataset)}")
    logger.info("Requesting %s %s through %s from CDS", var, start, end)
    started = time.perf_counter()
    with exclusive_download_lock(Path(cds_dir)):
        run_request(
            dataset,
            request,
            bundle,
            split_then_install({entry["short_name"]: target}, expected),
            client=client,
        )
    return target, time.perf_counter() - started


def _month_range(text: str) -> tuple[int, int]:
    first, _, last = text.partition("-")
    months = (int(first), int(last or first))
    if not 1 <= months[0] <= months[1] <= 12:
        raise argparse.ArgumentTypeError(f"not a month range within one year: {text}")
    return months


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--year", type=int, default=2000, help="Sample year to compare."
    )
    parser.add_argument(
        "--months",
        type=_month_range,
        default=(1, 12),
        help="Months of the sample year to compare, as FIRST-LAST (default 1-12).",
    )
    parser.add_argument(
        "--variable",
        action="append",
        choices=sorted(VARIABLE_REGISTRY),
        help="Variable to compare; repeat for several (default: every variable).",
    )
    parser.add_argument(
        "--from-cds",
        action="store_true",
        help=(
            "Request the CDS values fresh, one request per variable, and time each "
            "request, instead of reading the climatology yearly files. The mirror's "
            "rebuilt daily values are saved beside the CDS files for later checks."
        ),
    )
    parser.add_argument(
        "--cds-dir",
        type=Path,
        default=DEFAULT_CDS_DIR,
        help="Where --from-cds puts its CDS files (never the climatology directories).",
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


def main(argv=None, *, client=None) -> None:
    setup_logging()
    args = parse_args(argv)
    api_key = os.getenv(API_KEY_ENV_VAR)
    start, end = period_bounds(args.year, args.months)
    period = (
        str(args.year) if args.months == (1, 12) else f"{start} through {end}"
    )

    if not api_key:
        logger.warning("%s is not set; writing a 'not tested' report", API_KEY_ENV_VAR)
        args.report.write_text(render_report(period=period, tested=False))
        return

    store = open_mirror_store(api_key)
    results, skipped, timings = {}, {}, {}
    fetch_seconds = 0.0
    for var in args.variable or VARIABLE_REGISTRY:
        entry = VARIABLE_REGISTRY[var]
        cds_seconds = None
        if args.from_cds:
            path, cds_seconds = fetch_cds(var, start, end, args.cds_dir, client=client)
        else:
            path = climatology_file_path(var, args.year)
            if not path.exists():
                skipped[var] = f"CDS file not found: {path}"
                continue
        logger.info("Fetching %s for %s from the mirror", var, period)
        started = time.perf_counter()
        hourly = fetch_mirror(store, entry["short_name"], start, end)
        mirror_seconds = time.perf_counter() - started
        fetch_seconds += mirror_seconds
        if args.from_cds:
            timings[var] = (mirror_seconds, cds_seconds)

        if entry["daily_op"] == "sum":
            convention = args.accumulation
            if convention == "auto":
                convention = detect_accumulation_convention(hourly)
            daily = daily_totals(hourly, convention)
            rebuild = f"00:00 next day ({convention})"
        else:
            daily = daily_mean_6_hourly(hourly)
            rebuild = "mean of 00/06/12/18 UTC"

        if args.from_cds:
            saved = Path(args.cds_dir) / f"mirror_{var}_{start:%Y-%m}_to_{end:%Y-%m}.nc"
            daily.rename(entry["short_name"]).to_netcdf(saved)
            logger.info("Saved the mirror's daily %s values to %s", var, saved)
        stats = compare_values(daily, load_cds(path, var, start, end))
        stats["rebuild"] = rebuild
        results[var] = stats
        logger.info("%s: %s", var, stats)

    args.report.write_text(
        render_report(
            period=period,
            tested=True,
            results=results,
            skipped=skipped,
            fetch_seconds=fetch_seconds if results else None,
            cds_request_seconds=args.cds_request_seconds,
            timings=timings,
        )
    )
    logger.info("Report written to %s", args.report)


if __name__ == "__main__":
    main()
