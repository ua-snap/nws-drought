"""This script downloads daily ERA5 data. The most recent 365 days of available data will be downloaded.
"""

import logging
import shutil
import datetime
import cdsapi
from pathlib import Path
from config import (
    api_credentials_check,
    DEBUG_MODE,
    DATA_LAG_TIME_DAYS,
    DOWNLOAD_DIR,
    DL_BBOX,
)

api_credentials_check()


def set_download_directory():
    """Verify and/or create the directory structure for the data download."""
    if DEBUG_MODE:
        logging.info("Running in debug mode, no data will be fetched or overwritten.")
    else:
        # wipe the download directory and make a new one
        try:
            shutil.rmtree(DOWNLOAD_DIR)
        except:
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
    month = str(analysis_date.month)
    days = [str(x) for x in range(1, analysis_date.day + 1)]
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
    months = [str(x) for x in range(1, current_month)]
    days = [str(x) for x in range(1, 32)]
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
    months = [str(x) for x in range(1, 13)]
    days = [str(x) for x in range(1, 32)]
    logging.info(
        f"Trying to download data for the entire calendar year of {previous_year}..."
    )
    return previous_year, months, days


def download_data(year, months, days, data_variable, output_name):
    """Download ERA5 data via the CDS API client for a single data variable for the provided geographic area and dates. All 24 hours of data are downloaded.

    Args:
        year (list or str): YYYY string(s) to download
        months (list or str): MM string(s) to download
        days (list or str): DD string(s) to download
        data_variable (str): ERA5 data variable to download
        output_name (str): output name describing the time chunk downloaded
    """
    download_location = DOWNLOAD_DIR.joinpath(f"{data_variable}_{output_name}.nc")
    logging.info("Downloading data to %s", download_location)
    if not DEBUG_MODE:
        c = cdsapi.Client()
        c.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "format": "netcdf",
                "variable": data_variable,
                "year": year,
                "month": months,
                "day": days,
                "time": [
                    "0" + str(x) + ":00" if x <= 9 else str(x) + ":00"
                    for x in range(0, 24)
                ],
                "area": DL_BBOX,
            },
            download_location,
        )
    else:
        logging.info("CDS API download requests bypassed for debug mode.")


def run_all_downloads(data_variable):
    """A convenience function to download all necessary data for a given variable.

    Args:
        data_variable (str): ERA5 data variable to download
    """
    download_data(*get_current_month_dates(), data_variable, "current_month")
    download_data(*get_all_previous_year_dates(), data_variable, "previous_year")

    if analysis_date_not_in_january():
        download_data(*get_rest_of_current_year_dates(), data_variable, "current_year")


if __name__ == "__main__":

    # Log to STDOUT (+ STDERR)
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info("Running in %s mode", "DEBUG" if DEBUG_MODE else "production")

    set_download_directory()
    run_all_downloads("total_precipitation")
    run_all_downloads("snow_depth")
    run_all_downloads("volumetric_soil_water_layer_1")
    run_all_downloads("volumetric_soil_water_layer_2")
    run_all_downloads("potential_evaporation")
    logging.info("Download script completed.")
