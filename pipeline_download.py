"""This script downloads the necessary recent ERA5-Land data for drought indicator computation."""

import logging
import shutil

from config import RECENT_DATA_ROOT
from download_helpers import (
    analysis_date_not_in_january,
    download_recurring_era5_land_pipeline,
    get_all_previous_year_dates,
    get_current_month_dates,
    get_rest_of_current_year_dates,
)
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import setup_logging


def wipe_pipeline_directory():
    """Wipe the current set of pipeline data."""
    try:
        shutil.rmtree(RECENT_DATA_ROOT)
    except OSError:
        pass


def run_all_downloads(variable_key: str):
    """Download all time chunks for one pipeline variable.

    Args:
        variable_key (str): key in VARIABLE_REGISTRY (e.g. tp, swe, swvl1).
    """

    download_recurring_era5_land_pipeline(
        variable_key, "current_month", *get_current_month_dates()
    )

    download_recurring_era5_land_pipeline(
        variable_key, "previous_year", *get_all_previous_year_dates()
    )

    if analysis_date_not_in_january():
        download_recurring_era5_land_pipeline(
            variable_key, "current_year", *get_rest_of_current_year_dates()
        )


if __name__ == "__main__":
    setup_logging()

    for variable_key in VARIABLE_REGISTRY.keys():
        run_all_downloads(variable_key)
    logging.info("Pipeline download script completed.")
