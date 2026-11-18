import datetime
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

import cdsapi
import eccodes
import xarray as xr

from cds_requests import OutputCheckError
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


def _split_grib(bundle: Path, staged: dict[str, Path]) -> set[str]:
    """Copy each GRIB message whose shortName is in ``staged`` to that file.

    Messages are copied as raw bytes, never decoded and re-encoded, so values
    stay bit-identical to the download. Returns the shortNames found.
    """
    found = set()
    outputs = {}
    try:
        with open(bundle, "rb") as source:
            while (handle := eccodes.codes_grib_new_from_file(source)) is not None:
                try:
                    short_name = eccodes.codes_get(handle, "shortName")
                    if short_name not in staged:
                        logger.warning(
                            "%s holds unexpected variable %s; skipping it",
                            bundle.name,
                            short_name,
                        )
                        continue
                    if short_name not in outputs:
                        outputs[short_name] = open(staged[short_name], "wb")
                    outputs[short_name].write(eccodes.codes_get_message(handle))
                    found.add(short_name)
                finally:
                    eccodes.codes_release(handle)
    finally:
        for output in outputs.values():
            output.close()
    return found


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
    with open(bundle, "rb") as f:
        is_grib = f.read(4) == b"GRIB"
    if is_grib:
        return _split_grib(bundle, staged)
    found: set[str] = set()
    with tempfile.TemporaryDirectory(dir=bundle.parent) as work_dir:
        copy = Path(work_dir) / "single.nc"
        shutil.copyfile(bundle, copy)
        _place_netcdf(copy, staged, found)
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


def analysis_date_not_in_january():
    """Check if the date-of-analysis is not in January.

    Returns:
        (bool) indicating whether or not the analysis date is not in January.
    """
    if get_analysis_date().month == 1:
        return False
    else:
        return True


def get_current_month_dates():
    """Get the date information needed to download data from the current month of the current year, from the 1st of the month through the analysis date. This function exists because the CDS API does not gracefully handle data availability issues (the lag between today's date and the most recent date of ERA5 data). Batching this data request with any other month will trigger a CDS API error because it will try to fetch files that are not ready yet.

    Returns:
        year (str): YYYY string of the current year
        month (str): the current numerical month
        days (list): strings of numeric days 01 through the the analysis date
    """
    analysis_date = get_analysis_date()
    year = str(analysis_date.year)
    month = str(analysis_date.month).zfill(2)
    days = [str(x).zfill(2) for x in range(1, analysis_date.day + 1)]
    logger.info(
        f"Constructing date sequence for {month}/{year} for {len(days)} days between {days[0]} and {days[-1]}..."
    )
    return year, month, days


def get_rest_of_current_year_dates():
    """Get the date information needed to download data from the current year, starting with Jan 1st and ending at the month before the current month. This function does not need to be used if the analysis date is in January, assuming the current month (January) was downloaded first via get_current_month.

    Returns:
        current_year (str): YYYY string of the current year
        months (list): strings of numerical months, January through the previous month
        days (list): strings of numeric days 01 through 31
    """
    analysis_date = get_analysis_date()
    current_year = str(analysis_date.year)
    current_month = analysis_date.month
    months = [str(x).zfill(2) for x in range(1, current_month)]
    days = [str(x).zfill(2) for x in range(1, 32)]
    logger.info(
        f"Constructing date sequence for {current_year} for {len(months)} months between {months[0]} and {months[-1]}..."
    )
    return current_year, months, days


def get_all_previous_year_dates():
    """Get the date information needed to download data from the entire previous calendar year, January 1 through December 31.

    Returns:
        previous_year (str): YYYY string of the previous year
        months (list): strings of numerical months, January through December.
        days (list): strings of numeric days 01 through 31
    """
    analysis_date = get_analysis_date()
    previous_year = str(analysis_date.year - 1)
    months = _ALL_MONTHS
    days = _ALL_DAYS
    logger.info(
        f"Constructing date sequence for entire calendar year of {previous_year}..."
    )
    return previous_year, months, days


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


def download_era5_land_climatology(
    variable_key: str,
    start_year: int = 1981,
    end_year: int = 2021,
) -> None:
    """Download ERA5-Land for one variable over [start_year, end_year]."""
    variable_meta = VARIABLE_REGISTRY[variable_key]
    cds_variable = variable_meta["cds_variable"]
    prefix = variable_meta["prefix"]
    summary_method = variable_meta["daily_op"]
    dst_dir = variable_meta["climatology_dir"]
    suffix = variable_meta["suffix"]

    download_dir = BASELINE_DATA_ROOT / dst_dir
    download_dir.mkdir(parents=True, exist_ok=True)

    api_credentials_check()
    client = cdsapi.Client()

    for year in range(start_year, end_year + 1):
        logger.info(
            "Downloading %s (%s) for %s to %s",
            variable_key,
            cds_variable,
            year,
            download_dir,
        )
        if summary_method == "sum":
            cds_endpoint = _HOURLY_GRIB_ENDPOINT
            if year == 2021:
                # only Jan 1 at 00:00 is needed for the final climatology year:
                # it holds the 24-hour accumulation for Dec 31 of the prior year
                months, days = [_ALL_MONTHS[0]], [_ALL_DAYS[0]]
            else:
                months, days = _ALL_MONTHS, _ALL_DAYS
            request = _build_hourly_grib_request([cds_variable], year, months, days)
        if summary_method == "mean":
            cds_endpoint = _PREBAKED_DAILY_ENDPOINT
            request = _build_prebaked_daily_request(
                [cds_variable], year, _ALL_MONTHS, _ALL_DAYS
            )

        dst = download_dir / f"{prefix}{year}{suffix}"

        client.retrieve(cds_endpoint, request, target=dst)


def download_recurring_era5_land_pipeline(
    variable_key: str, time_chunk_tag: str, year: int, months: list, days: list
):
    """Download ERA5-Land for Computing the Drought Inidicators."""
    variable_meta = VARIABLE_REGISTRY[variable_key]
    cds_variable = variable_meta["cds_variable"]
    prefix = variable_meta["prefix"]
    summary_method = variable_meta["daily_op"]
    dst_dir = variable_meta["recent_dir"]
    suffix = variable_meta["suffix"]

    download_dir = RECENT_DATA_ROOT / dst_dir
    download_dir.mkdir(parents=True, exist_ok=True)

    api_credentials_check()
    client = cdsapi.Client()
    logger.info(
        "Downloading %s (%s) for %s to %s",
        variable_key,
        cds_variable,
        year,
        download_dir,
    )
    if summary_method == "sum":
        cds_endpoint = _HOURLY_GRIB_ENDPOINT
        request = _build_hourly_grib_request([cds_variable], year, months, days)
    if summary_method == "mean":
        cds_endpoint = _PREBAKED_DAILY_ENDPOINT
        request = _build_prebaked_daily_request([cds_variable], year, months, days)

    dst = download_dir / f"{prefix}{time_chunk_tag}{suffix}"
    client.retrieve(cds_endpoint, request, target=dst)
