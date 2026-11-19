import calendar
import contextlib
import datetime
import fcntl
import itertools
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import eccodes
import xarray as xr

from cds_requests import OutputCheckError, run_request
from config import BASELINE_DATA_ROOT, DATA_LAG_TIME_DAYS, DL_BBOX, RECENT_DATA_ROOT
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, check_output_file

logger = logging.getLogger(__name__)


_PREBAKED_DAILY_ENDPOINT = "derived-era5-land-daily-statistics"
_HOURLY_GRIB_ENDPOINT = "reanalysis-era5-land"

_ALL_MONTHS = [str(month).zfill(2) for month in range(1, 13)]
_ALL_DAYS = [str(day).zfill(2) for day in range(1, 32)]
_ALL_HOURS = [f"{hour:02d}:00" for hour in range(24)]

# the 00:00 UTC value on date D+1 is the 24-hour accumulation for date D
_ACCUMULATION_FOR_PRIOR_24HRS = "00:00"

# daily totals are built from the hourly accumulations; daily means come
# ready-made from the daily-statistics dataset
_DATASET_FOR_DAILY_OP = {
    "sum": _HOURLY_GRIB_ENDPOINT,
    "mean": _PREBAKED_DAILY_ENDPOINT,
}


def group_variables_by_dataset(variable_keys=None) -> dict[str, list[str]]:
    """Group registry keys by the CDS dataset that serves them, so one request
    per dataset can fetch every variable it holds.

    Args:
        variable_keys: registry keys to group (default: every registry variable).
    Returns:
        {dataset name: [registry keys in registry order]}
    """
    keys = VARIABLE_REGISTRY if variable_keys is None else variable_keys
    groups: dict[str, list[str]] = {}
    for key in keys:
        dataset = _DATASET_FOR_DAILY_OP[VARIABLE_REGISTRY[key]["daily_op"]]
        groups.setdefault(dataset, []).append(key)
    return groups


# CDS refuses a daily-statistics request for three variables over a whole
# year ("cost limits exceeded"); one variable over a whole year is accepted.
# Requests to a capped dataset hold at most this many variables x months.
_MAX_VARIABLE_MONTHS = {_PREBAKED_DAILY_ENDPOINT: 12}


def _chunks(items, size: int) -> list[tuple]:
    items = tuple(items)
    return [items[i : i + size] for i in range(0, len(items), size)]


def months_per_request(dataset: str, n_variables: int, n_months: int) -> int:
    """Most months one request for ``n_variables`` can hold without passing
    the dataset's CDS cost limit (at least 1)."""
    cap = _MAX_VARIABLE_MONTHS.get(dataset)
    if cap is None:
        return n_months
    return max(1, cap // n_variables)


def variable_groups_per_request(
    dataset: str, variable_keys, n_months: int
) -> list[tuple[str, ...]]:
    """Split variables into groups small enough to request ``n_months`` months
    together within the dataset's CDS cost limit."""
    cap = _MAX_VARIABLE_MONTHS.get(dataset)
    if cap is None:
        return [tuple(variable_keys)] if variable_keys else []
    return _chunks(variable_keys, max(1, cap // n_months))


def _build_hourly_grib_request(
    cds_variables: list, year: int, months: list, days: list
) -> dict:
    """Build a request for the hourly GRIB endpoint, scoped to the given months/days.

    Note that the 00:00 UTC value on date D is the 24-hour accumulation for date
    D-1, and CDS treats the requested day list as valid times. A request for days
    01..N therefore yields accumulations for the last day of the previous month
    through day N-1, each labeled by its valid_time (01..N). This matches the
    convention used when building the climatology, so no day-window extension is
    applied here.
    """
    return {
        "variable": list(cds_variables),
        "year": str(year),
        "month": months,
        "day": days,
        "time": _ACCUMULATION_FOR_PRIOR_24HRS,
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def _build_prebaked_daily_request(
    cds_variables: list, year: int, months: list, days: list
) -> dict:
    return {
        "variable": list(cds_variables),
        "year": str(year),
        "month": months,
        "day": days,
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": DL_BBOX,
    }


def _copy_grib_messages(
    bundle: Path, staged: dict, key_of: Callable[[int], object], what: str
) -> set:
    """Copy each GRIB message to ``staged[key_of(handle)]``.

    Messages are copied as raw bytes, never decoded and re-encoded, so values
    stay bit-identical to the download. Messages whose key is not in ``staged``
    are skipped with a warning. Returns the keys found.
    """
    found = set()
    outputs = {}
    try:
        with open(bundle, "rb") as source:
            while (handle := eccodes.codes_grib_new_from_file(source)) is not None:
                try:
                    key = key_of(handle)
                    if key not in staged:
                        logger.warning(
                            "%s holds unexpected %s %s; skipping it",
                            bundle.name,
                            what,
                            key,
                        )
                        continue
                    if key not in outputs:
                        outputs[key] = open(staged[key], "wb")
                    outputs[key].write(eccodes.codes_get_message(handle))
                    found.add(key)
                finally:
                    eccodes.codes_release(handle)
    finally:
        for output in outputs.values():
            output.close()
    return found


def _split_grib(bundle: Path, staged: dict[str, Path]) -> set[str]:
    """Copy each GRIB message whose shortName is in ``staged`` to that file."""
    return _copy_grib_messages(
        bundle,
        staged,
        lambda handle: eccodes.codes_get(handle, "shortName"),
        "variable",
    )


def build_cds_request(
    dataset: str, variable_keys, year: int, months: list, days: list
) -> dict:
    """The CDS request for registry variables of one dataset."""
    cds_variables = [VARIABLE_REGISTRY[key]["cds_variable"] for key in variable_keys]
    build = (
        _build_hourly_grib_request
        if dataset == _HOURLY_GRIB_ENDPOINT
        else _build_prebaked_daily_request
    )
    return build(cds_variables, year, months, days)


def bundle_suffix(dataset: str) -> str:
    """File suffix of a combined download: hourly data arrives as GRIB, daily
    statistics as a zip of netCDF files."""
    return ".grib" if dataset == _HOURLY_GRIB_ENDPOINT else ".zip"


def _file_needs_download(path: Path, short_name: str, expected_dates) -> bool:
    ok, reason = check_output_file(path, short_name, expected_dates)
    if ok:
        return False
    if path.exists():
        logger.warning("%s failed its check (%s); will replace it", path, reason)
    else:
        logger.info("%s is missing; will download it", path)
    return True


def _grib_valid_month(handle: int) -> tuple[int, int]:
    # validityDate is the date cfgrib reports as valid_time (YYYYMMDD)
    validity_date = eccodes.codes_get(handle, "validityDate")
    return validity_date // 10000, validity_date // 100 % 100


def _is_grib(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(4) == b"GRIB"


def _netcdf_variables(path: Path) -> set[str]:
    with xr.open_dataset(path, engine=NETCDF_ENGINE) as ds:
        return set(ds.data_vars)


def _place_netcdf(path: Path, staged: dict[str, Path], found: set[str]) -> None:
    """Move a single-variable netCDF to the staged path for the variable it holds,
    identified by opening it rather than trusting its name."""
    matches = _netcdf_variables(path) & staged.keys()
    if len(matches) != 1:
        logger.warning(
            "%s holds none or several of %s; skipping it", path.name, sorted(staged)
        )
        return
    short_name = matches.pop()
    shutil.move(path, staged[short_name])
    found.add(short_name)


def _split_zip(bundle: Path, staged: dict[str, Path]) -> set[str]:
    """Unpack a zip of one netCDF per variable into the staged paths."""
    found: set[str] = set()
    with tempfile.TemporaryDirectory(dir=bundle.parent) as work_dir:
        with zipfile.ZipFile(bundle) as archive:
            for index, member in enumerate(archive.infolist()):
                if member.is_dir():
                    continue
                # write under our own name so a member path cannot escape work_dir
                extracted = Path(work_dir) / f"member_{index}.nc"
                with archive.open(member) as src, open(extracted, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                _place_netcdf(extracted, staged, found)
    return found


def _split_bundle(bundle: Path, staged: dict[str, Path]) -> set[str]:
    """Split a download into the staged per-variable files, choosing GRIB, zip or
    bare netCDF from the file's content (a one-variable daily-statistics request
    may come back as a bare netCDF rather than a zip)."""
    if zipfile.is_zipfile(bundle):
        return _split_zip(bundle, staged)
    if _is_grib(bundle):
        return _split_grib(bundle, staged)
    found: set[str] = set()
    # the download is a throwaway temporary file, so it can be moved as is
    _place_netcdf(bundle, staged, found)
    return found


def split_then_install(
    targets: dict[str, Path], expected_dates: list
) -> Callable[[Path], None]:
    """Build a finalize step for a combined (several-variable) download.

    The step splits the downloaded bundle into one file per variable, checks
    every split file for its variable and ``expected_dates`` and, only if every
    expected variable is present and passes, moves each into place. Otherwise it
    removes the split files and raises ``OutputCheckError`` (so the request runner
    resubmits) without installing anything.

    Args:
        targets: {registry short_name (GRIB shortName or netCDF variable name):
            final path for that variable's file}
        expected_dates: valid dates each split file must hold exactly.
    """
    targets = {name: Path(path) for name, path in targets.items()}

    def finalize(bundle: Path) -> None:
        bundle = Path(bundle)
        staged = {}
        for short_name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            staged[short_name] = target.with_name(f"{target.stem}.split{target.suffix}")
        try:
            found = _split_bundle(bundle, staged)
            missing = sorted(targets.keys() - found)
            if missing:
                raise OutputCheckError(
                    f"{bundle.name} is missing expected variables {missing}"
                )
            for short_name, path in staged.items():
                ok, reason = check_output_file(path, short_name, expected_dates)
                if not ok:
                    raise OutputCheckError(f"{targets[short_name]}: {reason}")
            for short_name, path in staged.items():
                path.replace(targets[short_name])
                logger.info("Installed %s", targets[short_name])
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)

    return finalize


def _split_netcdf_by_month(path: Path, staged: dict[tuple, Path]) -> set[tuple]:
    """Write each calendar month of a one-variable netCDF to ``staged[(y, m)]``.

    The file is subset in its stored form (no CF decoding), so the stored
    numbers, their dtype and the packing and fill attributes are written back
    unchanged and decode to exactly the downloaded values.
    """
    with xr.open_dataset(path, engine=NETCDF_ENGINE) as decoded:
        months = decoded["valid_time"].values.astype("datetime64[M]")
    found = set()
    with xr.open_dataset(path, engine=NETCDF_ENGINE, decode_cf=False) as raw:
        for month in sorted(set(months)):
            year_month = (month.item().year, month.item().month)
            if year_month not in staged:
                logger.warning(
                    "%s holds unexpected month %s; skipping it", path.name, month
                )
                continue
            raw.isel(valid_time=(months == month).nonzero()[0]).to_netcdf(
                staged[year_month], engine=NETCDF_ENGINE
            )
            found.add(year_month)
    return found


def _split_by_month(path: Path, staged: dict[tuple, Path]) -> set[tuple]:
    if _is_grib(path):
        return _copy_grib_messages(path, staged, _grib_valid_month, "month")
    return _split_netcdf_by_month(path, staged)


def split_months_then_install(
    targets: dict[str, dict[tuple[int, int], Path]],
    expected_dates: dict[tuple[int, int], list],
) -> Callable[[Path], None]:
    """Build a finalize step for a download covering several variables and months.

    The step splits the bundle into one file per variable, then each of those
    into one file per calendar month (GRIB messages copied byte for byte;
    netCDF subset without decoding), checks every month file for its variable
    and that month's ``expected_dates`` and, only if all pass, moves each into
    place. Otherwise it removes the split files and raises ``OutputCheckError``
    without installing anything.

    Args:
        targets: {registry short_name: {(year, month): final path}}
        expected_dates: {(year, month): valid dates that month's files must hold}
    """
    targets = {
        name: {month: Path(path) for month, path in by_month.items()}
        for name, by_month in targets.items()
    }

    def finalize(bundle: Path) -> None:
        bundle = Path(bundle)
        staged = {}
        for name, by_month in targets.items():
            for month, target in by_month.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                staged[name, month] = target.with_name(
                    f"{target.stem}.split{target.suffix}"
                )
        try:
            with tempfile.TemporaryDirectory(dir=bundle.parent) as work_dir:
                per_variable = {
                    name: Path(work_dir)
                    / f"{name}{next(iter(by_month.values())).suffix}"
                    for name, by_month in targets.items()
                }
                found = _split_bundle(bundle, per_variable)
                missing = sorted(targets.keys() - found)
                if missing:
                    raise OutputCheckError(
                        f"{bundle.name} is missing expected variables {missing}"
                    )
                for name, path in per_variable.items():
                    _split_by_month(
                        path, {month: staged[name, month] for month in targets[name]}
                    )
            for (name, month), path in staged.items():
                ok, reason = check_output_file(path, name, expected_dates[month])
                if not ok:
                    raise OutputCheckError(f"{targets[name][month]}: {reason}")
            for (name, month), path in staged.items():
                path.replace(targets[name][month])
                logger.info("Installed %s", targets[name][month])
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)

    return finalize


def api_credentials_check():
    cds_api_prompt = "Climate Data Store API credentials were not found in your $HOME directory. Please verify and store a valid API key in a .cdsapirc file and visit https://cds.climate.copernicus.eu/api-how-to#install-the-cds-api-key for instructions."
    assert ".cdsapirc" in os.listdir(os.environ["HOME"]), cds_api_prompt


def get_analysis_date():
    """Create a date-of-analysis for which the prior 365 days will have their data fetched.
    We use this lagged date because data is not available in real-time.

    Returns:
        analysis_date (datetime object): date to mark and structure the data download
    """
    analysis_date = datetime.date.today() - datetime.timedelta(days=DATA_LAG_TIME_DAYS)
    logger.info(f"Establishing the analysis date for the data as {analysis_date}")
    return analysis_date


# Climatology: one yearly file per variable, 1981 through 2021, fetched by one
# job that sends one request per dataset per year with the variables combined,
# except where a dataset's CDS cost limit splits them (_MAX_VARIABLE_MONTHS).
_CLIMATOLOGY_START_YEAR = 1981
_CLIMATOLOGY_END_YEAR = 2021
# Only January 1 is fetched for the summed variables in the final year: its
# 00:00 value is the total for December 31 of the year before. The mean
# variables fetch the whole final year.
_FINAL_CLIMATOLOGY_YEAR = 2021

# One request per dataset per calendar year. This shape is kept unless the
# request-size benchmark (baseline_data_generation_scripts/
# benchmark_request_shapes.py) shows 12 monthly requests finishing sooner in
# both of its rounds; a single queue swing should not switch the rebuild to
# 12 times as many requests.
CLIMATOLOGY_REQUEST_SHAPE = "yearly"


def climatology_file_path(variable_key: str, year: int) -> Path:
    """Yearly climatology file for one variable:
    ``<climatology_dir>/<prefix><YYYY><suffix>`` under BASELINE_DATA_ROOT."""
    meta = VARIABLE_REGISTRY[variable_key]
    return (
        BASELINE_DATA_ROOT
        / meta["climatology_dir"]
        / f"{meta['prefix']}{year}{meta['suffix']}"
    )


def _climatology_months_and_days(dataset: str, year: int) -> tuple[list, list]:
    if dataset == _HOURLY_GRIB_ENDPOINT and year == _FINAL_CLIMATOLOGY_YEAR:
        return [_ALL_MONTHS[0]], [_ALL_DAYS[0]]
    return _ALL_MONTHS, _ALL_DAYS


@dataclass(frozen=True)
class ClimatologyRequest:
    """One CDS request for some variables of a dataset over one year."""

    dataset: str
    variable_keys: tuple[str, ...]
    year: int

    def cds_request(self) -> dict:
        months, days = _climatology_months_and_days(self.dataset, self.year)
        return build_cds_request(
            self.dataset, self.variable_keys, self.year, months, days
        )

    def expected_dates(self) -> list[str]:
        """Valid dates each yearly file holds: every day of the year (for the
        summed variables, January 1 holds the previous year's December 31
        total), or only January 1 for the summed variables' final year."""
        _, days = _climatology_months_and_days(self.dataset, self.year)
        if days == [_ALL_DAYS[0]]:
            return [datetime.date(self.year, 1, 1).isoformat()]
        return [
            date for month in range(1, 13) for date in month_dates(self.year, month)
        ]

    def targets(self) -> dict[str, Path]:
        return {
            VARIABLE_REGISTRY[key]["short_name"]: climatology_file_path(key, self.year)
            for key in self.variable_keys
        }

    def bundle_target(self) -> Path:
        """Download name, stable for a dataset and year so a restarted job
        finds the request it saved."""
        return (
            BASELINE_DATA_ROOT
            / _BUNDLE_DIR
            / (
                f"{self.dataset}_{self.year}_{'-'.join(self.variable_keys)}"
                f"{bundle_suffix(self.dataset)}"
            )
        )


def plan_climatology_requests(
    variable_keys=None,
    start_year: int = _CLIMATOLOGY_START_YEAR,
    end_year: int = _CLIMATOLOGY_END_YEAR,
) -> list[ClimatologyRequest]:
    """The climatology requests still needed, oldest year first.

    For each year and dataset, variables whose yearly file passes the output
    check are skipped; the rest are fetched in one combined request, or in
    several where the dataset's CDS cost limit requires it (one variable per
    request for daily statistics). Every failing file is logged.
    """
    requests = []
    for year in range(start_year, end_year + 1):
        for dataset, keys in group_variables_by_dataset(variable_keys).items():
            request = ClimatologyRequest(dataset, tuple(keys), year)
            expected = request.expected_dates()
            needed = [
                key
                for key in keys
                if _file_needs_download(
                    climatology_file_path(key, year),
                    VARIABLE_REGISTRY[key]["short_name"],
                    expected,
                )
            ]
            for group in variable_groups_per_request(dataset, needed, 12):
                requests.append(ClimatologyRequest(dataset, group, year))
    return requests


def download_era5_land_climatology(
    variable_keys=None,
    start_year: int = _CLIMATOLOGY_START_YEAR,
    end_year: int = _CLIMATOLOGY_END_YEAR,
    *,
    client=None,
) -> None:
    """Download the ERA5-Land climatology, one CDS request at a time.

    Yearly files that already pass the output check are kept, so running the
    job again after a stop continues where it stopped, and a job still queued
    at CDS is reattached rather than submitted again.

    Args:
        variable_keys: registry keys to download (default: every variable).
        start_year, end_year: inclusive range of years.
        client: datastores client for the request runner (default: built from
            cdsapi's configuration).
    """
    with exclusive_download_lock(BASELINE_DATA_ROOT / _BUNDLE_DIR):
        requests = plan_climatology_requests(variable_keys, start_year, end_year)
        logger.info(
            "Climatology download %d-%d: %d %s CDS requests",
            start_year,
            end_year,
            len(requests),
            CLIMATOLOGY_REQUEST_SHAPE,
        )
        for request in requests:
            target = request.bundle_target()
            target.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Requesting %s (%s) for %d",
                request.dataset,
                ",".join(request.variable_keys),
                request.year,
            )
            run_request(
                request.dataset,
                request.cds_request(),
                target,
                split_then_install(request.targets(), request.expected_dates()),
                client=client,
            )


# Recurring download: one file per variable per month, covering January 1 of
# the previous year through the analysis date. Each run re-downloads the
# current month and the completed months still inside the window in which
# ERA5-Land's preliminary data can be replaced by final data (about 2 months,
# plus one month of margin). Older months are reused when their files pass
# the output check.
_RECURRING_WINDOW_MONTHS = 3
_BUNDLE_DIR = "cds_downloads"


@contextlib.contextmanager
def exclusive_download_lock(directory: Path):
    """Hold an exclusive lock on ``directory`` for one download run.

    Two runs sharing a download directory would reuse each other's saved
    request IDs and delete each other's CDS jobs, and ECMWF asks for one
    request at a time per account, so a second run stops before submitting.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".lock", "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                f"Another CDS download is already running in {directory}; "
                "wait for it to finish before starting this one."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def coverage_months(analysis_date: datetime.date) -> list[tuple[int, int]]:
    """(year, month) pairs from January of the previous year through the
    analysis date's month, in order."""
    return [
        (year, month)
        for year in (analysis_date.year - 1, analysis_date.year)
        for month in range(1, 13)
        if (year, month) <= (analysis_date.year, analysis_date.month)
    ]


def month_dates(year: int, month: int, last_day: int | None = None) -> list[str]:
    """ISO dates of a month, from the 1st through ``last_day`` (default: the
    month's last day). For the summed variables these are the 00:00 valid
    dates, so a month's file holds the previous month's last-day total on
    the 1st and its own last day's total arrives in the next month's file."""
    month_length = calendar.monthrange(year, month)[1]
    last = month_length if last_day is None else min(last_day, month_length)
    return [datetime.date(year, month, day).isoformat() for day in range(1, last + 1)]


def monthly_file_path(variable_key: str, year: int, month: int) -> Path:
    """Recurring file for one variable and month:
    ``<recent_dir>/<prefix><YYYY>-<MM><suffix>`` under RECENT_DATA_ROOT."""
    meta = VARIABLE_REGISTRY[variable_key]
    return (
        RECENT_DATA_ROOT
        / meta["recent_dir"]
        / f"{meta['prefix']}{year}-{month:02d}{meta['suffix']}"
    )


def recurring_monthly_files(
    variable_key: str, analysis_date: datetime.date
) -> list[Path]:
    """The monthly files a recurring run keeps for one variable, oldest first."""
    return [
        monthly_file_path(variable_key, year, month)
        for year, month in coverage_months(analysis_date)
    ]


@dataclass(frozen=True)
class MonthlyRequest:
    """One CDS request for every variable of a dataset over months of one year."""

    dataset: str
    variable_keys: tuple[str, ...]
    year: int
    months: tuple[int, ...]
    days: tuple[str, ...]

    def cds_request(self) -> dict:
        months = [f"{month:02d}" for month in self.months]
        return build_cds_request(
            self.dataset, self.variable_keys, self.year, months, list(self.days)
        )

    def expected_dates(self) -> dict[tuple[int, int], list[str]]:
        last_day = int(self.days[-1])
        return {
            (self.year, month): month_dates(self.year, month, last_day)
            for month in self.months
        }

    def month_targets(self) -> dict[str, dict[tuple[int, int], Path]]:
        return {
            VARIABLE_REGISTRY[key]["short_name"]: {
                (self.year, month): monthly_file_path(key, self.year, month)
                for month in self.months
            }
            for key in self.variable_keys
        }

    def bundle_target(self) -> Path:
        """Download name, stable for a dataset and month set so a restarted run
        finds the request it saved."""
        months = "-".join(f"{month:02d}" for month in self.months)
        return (
            RECENT_DATA_ROOT
            / _BUNDLE_DIR
            / f"{self.dataset}_{self.year}_{months}{bundle_suffix(self.dataset)}"
        )


def _month_needs_download(variable_keys, year: int, month: int) -> bool:
    """True if any variable's file for the month is missing or fails the check.
    Every failing file is logged."""
    # check every variable (no short-circuit) so each failing file is logged
    results = [
        _file_needs_download(
            monthly_file_path(key, year, month),
            VARIABLE_REGISTRY[key]["short_name"],
            month_dates(year, month),
        )
        for key in variable_keys
    ]
    return any(results)


def plan_recurring_requests(analysis_date: datetime.date) -> list[MonthlyRequest]:
    """Group the months a recurring run must fetch into CDS requests.

    Per dataset: older months whose files are missing or fail the check, one
    request per calendar year; the completed months inside the re-download
    window, one request per calendar year; a year's months are split further
    into blocks where the dataset's CDS cost limit requires it (4 months for
    the three daily-statistics variables); and the current month, days 01
    through the analysis day, on its own (CDS errors on days not yet
    available). When one variable's file for a month fails, the month is
    requested for every variable of that dataset.
    """
    months = coverage_months(analysis_date)
    *completed, (year, month) = months
    window = completed[-_RECURRING_WINDOW_MONTHS:]
    older = completed[:-_RECURRING_WINDOW_MONTHS]
    current_days = tuple(f"{day:02d}" for day in range(1, analysis_date.day + 1))

    requests = []
    for dataset, keys in group_variables_by_dataset().items():
        keys = tuple(keys)
        backfill = [m for m in older if _month_needs_download(keys, *m)]
        for group in (backfill, window):
            for group_year, in_year in itertools.groupby(group, key=lambda m: m[0]):
                in_year = [m for _, m in in_year]
                size = months_per_request(dataset, len(keys), len(in_year))
                for block in _chunks(in_year, size):
                    requests.append(
                        MonthlyRequest(
                            dataset, keys, group_year, block, tuple(_ALL_DAYS)
                        )
                    )
        requests.append(MonthlyRequest(dataset, keys, year, (month,), current_days))
    return requests


def download_recurring_era5_land(
    analysis_date: datetime.date | None = None, *, client=None
) -> None:
    """Download the recurring ERA5-Land months, one CDS request at a time.

    Args:
        analysis_date: last date to download (default: ``get_analysis_date()``).
        client: datastores client for the request runner (default: built from
            cdsapi's configuration).
    """
    if analysis_date is None:
        analysis_date = get_analysis_date()
    with exclusive_download_lock(RECENT_DATA_ROOT / _BUNDLE_DIR):
        requests = plan_recurring_requests(analysis_date)
        logger.info(
            "Recurring download for analysis date %s: %d CDS requests",
            analysis_date,
            len(requests),
        )
        for request in requests:
            target = request.bundle_target()
            target.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Requesting %s (%s) for %d, months %s, days %s-%s",
                request.dataset,
                ",".join(request.variable_keys),
                request.year,
                ",".join(f"{m:02d}" for m in request.months),
                request.days[0],
                request.days[-1],
            )
            run_request(
                request.dataset,
                request.cds_request(),
                target,
                split_months_then_install(
                    request.month_targets(), request.expected_dates()
                ),
                client=client,
            )
