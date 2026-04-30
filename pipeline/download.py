"""This script downloads hourly ERA5-Land data for the most recent 365 days for which data is available."""

import datetime
import logging
import shutil

import cdsapi
import luts
from config import (
    DATA_LAG_TIME_DAYS,
    DEBUG_MODE,
    DL_BBOX,
    DOWNLOAD_DIR,
    api_credentials_check,
)
from nws_drought.era5_land.registry import VARIABLE_REGISTRY

api_credentials_check()

_HOURLY_TIMES = [f"{hour:02d}:00" for hour in range(24)]

# Maps registry keys to luts.varname_prefix_lu keys (output stems match process.py / luts).
_REGISTRY_TO_LUT_KEY = {
    "tp": "tp",
    "pev": "pev",
    "swe": "sd",
    "swvl1": "swvl1",
    "swvl2": "swvl2",
}

_PIPELINE_VARIABLE_ORDER = ("tp", "swe", "swvl1", "swvl2", "pev")


def set_download_directory():
    """Verify and/or create the directory structure for the data download."""
    if DEBUG_MODE:
        logging.info("Running in debug mode, no data will be fetched or overwritten.")
    else:
        try:
            shutil.rmtree(DOWNLOAD_DIR)
        except OSError:
            pass

        DOWNLOAD_DIR.mkdir(exist_ok=False, parents=True)


def get_analysis_date():
    """Create a date-of-analysis for which the prior 365 days will have their data fetched. We use this lagged date because data is not available in real-time.

    Returns:
        analysis_date (datetime object): date to mark and structure the data download
    """
    analysis_date = datetime.date.today() - datetime.timedelta(days=DATA_LAG_TIME_DAYS)
    logging.info("Downloading last 365 days of data before %s", analysis_date)
    return analysis_date


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
        f"Trying to download data for {month}/{year} for {len(days)} days between {days[0]} and {days[-1]}..."
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
        f"Trying to download data for {current_year} for {len(months)} months between {months[0]} and {months[-1]}..."
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
    months = [str(x).zfill(2) for x in range(1, 13)]
    days = [str(x).zfill(2) for x in range(1, 32)]
    logging.info(
        f"Trying to download data for the entire calendar year of {previous_year}..."
    )
    return previous_year, months, days


def download_data(year, months, days, cds_variable, output_stem, output_name):
    """Download ERA5-Land hourly GRIB via the CDS API for one variable and date selection.

    Args:
        year (list or str): YYYY string(s) to download
        months (list or str): MM string(s) to download
        days (list or str): DD string(s) to download
        cds_variable (str): ERA5-Land CDS variable name
        output_stem (str): filename stem matching luts.varname_prefix_lu (for process.py)
        output_name (str): time chunk label (current_month, previous_year, current_year)
    """
    download_location = DOWNLOAD_DIR.joinpath(f"{output_stem}_{output_name}.grib")
    logging.info("Downloading data to %s", download_location)
    if not DEBUG_MODE:
        client = cdsapi.Client()
        client.retrieve(
            "reanalysis-era5-land",
            {
                "variable": cds_variable,
                "year": year,
                "month": months,
                "day": days,
                "time": list(_HOURLY_TIMES),
                "data_format": "grib",
                "download_format": "unarchived",
                "area": DL_BBOX,
            },
            str(download_location),
        )
    else:
        logging.info("CDS API download requests bypassed for debug mode.")


def run_all_downloads(registry_key: str):
    """Download all time chunks for one pipeline variable (registry key).

    Args:
        registry_key (str): key in VARIABLE_REGISTRY (e.g. tp, swe, swvl1).
    """
    cds_variable = VARIABLE_REGISTRY[registry_key]["cds_variable"]
    output_stem = luts.varname_prefix_lu[_REGISTRY_TO_LUT_KEY[registry_key]]
    download_data(
        *get_current_month_dates(), cds_variable, output_stem, "current_month"
    )
    download_data(
        *get_all_previous_year_dates(), cds_variable, output_stem, "previous_year"
    )

    if analysis_date_not_in_january():
        download_data(
            *get_rest_of_current_year_dates(),
            cds_variable,
            output_stem,
            "current_year",
        )


if __name__ == "__main__":

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("Running in %s mode", "DEBUG" if DEBUG_MODE else "production")

    set_download_directory()
    for _key in _PIPELINE_VARIABLE_ORDER:
        run_all_downloads(_key)
    logging.info("Download script completed.")
