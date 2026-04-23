"""Helpers for requesting the 2021 CDS boundary day used for backfill."""

import cdsapi
from config import DL_BBOX

from era5_land_variable_registry import (
    VARIABLE_REGISTRY,
)

_HOURLY_TIMES = [f"{hour:02d}:00" for hour in range(24)]


def hourly_grib_filename(variable, year):
    """Return the hourly GRIB filename used by the existing archive."""
    return f"{VARIABLE_REGISTRY[variable]['hourly_prefix']}{year}.grib"


def build_boundary_request(variable):
    """Return the fixed one-day CDS request payload for 2021-01-01."""
    return {
        "variable": VARIABLE_REGISTRY[variable]["cds_variable"],
        "year": 2021,
        "month": [1],
        "day": [1],
        "time": list(_HOURLY_TIMES),
        "data_format": "grib",
        "download_format": "unarchived",
        "area": DL_BBOX,
    }


def download_2021_for_backfill(variable):
    """Download the 2021 CDS boundary day for the given variable."""
    request = build_boundary_request(variable)
    client = cdsapi.Client()
    client.retrieve(
        "reanalysis-era5-land",
        request,
        hourly_grib_filename(variable, 2021),
    )


if __name__ == "__main__":
    # download all the variables
    for variable in VARIABLE_REGISTRY.keys():
        download_2021_for_backfill(variable)
