import datetime
import logging
import os

import cdsapi

from config import BASELINE_DATA_ROOT, DATA_LAG_TIME_DAYS, DL_BBOX, RECENT_DATA_ROOT
from era5_land_variable_registry import VARIABLE_REGISTRY

_PREBAKED_DAILY_ENDPOINT = "derived-era5-land-daily-statistics"
_HOURLY_GRIB_ENDPOINT = "reanalysis-era5-land"

_ALL_MONTHS = [str(month).zfill(2) for month in range(1, 13)]
_ALL_DAYS = [str(day).zfill(2) for day in range(1, 32)]
_ALL_HOURS = [f"{hour:02d}:00" for hour in range(24)]

# the 00:00 UTC value on date D+1 is the 24-hour accumulation for date D
_ACCUMULATION_FOR_PRIOR_24HRS = "00:00"


def _build_hourly_grib_request(cds_variable: str, year: int) -> dict:
    if year == 2021:
        days = _ALL_DAYS[0]
        months = _ALL_MONTHS[0]
    else:
        days = _ALL_DAYS
        months = _ALL_MONTHS
    return {
        "variable": cds_variable,
        "year": str(year),
        "month": months,
        "day": days,
        "time": _ACCUMULATION_FOR_PRIOR_24HRS,
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def _build_prebaked_daily_request(cds_variable: str, year: int) -> dict:
    return {
        "variable": cds_variable,
        "year": str(year),
        "month": _ALL_MONTHS,
        "day": _ALL_DAYS,
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": DL_BBOX,
    }


def _pipeline_build_hourly_grib_request(cds_variable: str, year: int) -> dict:
    if year == 2021:
        days = _ALL_DAYS[0]
        months = _ALL_MONTHS[0]
    else:
        days = _ALL_DAYS
        months = _ALL_MONTHS
    return {
        "variable": cds_variable,
        "year": str(year),
        "month": months,
        "day": days,
        "time": _ACCUMULATION_FOR_PRIOR_24HRS,
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def _pipeline_build_prebaked_daily_request(
    cds_variable: str, year: int, months, days
) -> dict:
    return {
        "variable": cds_variable,
        "year": str(year),
        "month": months,
        "day": days,
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": DL_BBOX,
    }


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
    logging.info(
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
    logging.info(
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
    logging.info(
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
    logging.info(f"Establishing the analysis date for the data as {analysis_date}")
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
        logging.info(
            "Downloading %s (%s) for %s to %s",
            variable_key,
            cds_variable,
            year,
            download_dir,
        )
        if summary_method == "sum":
            cds_endpoint = _HOURLY_GRIB_ENDPOINT
            request = _build_hourly_grib_request(cds_variable, year)
        if summary_method == "mean":
            cds_endpoint = _PREBAKED_DAILY_ENDPOINT
            request = _build_prebaked_daily_request(cds_variable, year)

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
    dst_dir = variable_meta["climatology_dir"]
    suffix = variable_meta["suffix"]

    download_dir = RECENT_DATA_ROOT / dst_dir
    download_dir.mkdir(parents=True, exist_ok=True)

    api_credentials_check()
    client = cdsapi.Client()
    logging.info(
        "Downloading %s (%s) for %s to %s",
        variable_key,
        cds_variable,
        year,
        download_dir,
    )
    if summary_method == "sum":
        cds_endpoint = _HOURLY_GRIB_ENDPOINT
        request = _pipeline_build_hourly_grib_request(cds_variable, year)
    if summary_method == "mean":
        cds_endpoint = _PREBAKED_DAILY_ENDPOINT
        request = _pipeline_build_prebaked_daily_request(
            cds_variable, year, months, days
        )

    dst = download_dir / f"{prefix}{time_chunk_tag}{suffix}"
    client.retrieve(cds_endpoint, request, target=dst)
