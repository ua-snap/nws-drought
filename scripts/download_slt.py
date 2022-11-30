"""This is the script that was used to download the ERA5 soil type variable that is constant through time and will be provided alongside the other fixed inputs (e.g. climatoglogies). Provided here for reference and should not be needed by NWS/NOAA.
"""

import os
import logging
import cdsapi
from config import (
    api_credentials_check,
    DL_BBOX,
)

api_credentials_check()


def download_soil_type():
    """Download a single observation of soil type data to current working directory"""
    logging.info(f"Downloading soil type data to {os.getcwd()}")
    c = cdsapi.Client()
    c.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": "reanalysis",
            "format": "netcdf",
            "variable": "soil_type",
            "year": "2022",
            "month": "01",
            "day": "01",
            "time": "00:00",
            "area": DL_BBOX,
        },
        "soil_type.nc",
    )
    
    return

    
if __name__ == "__main__":
    # Log to STDOUT (+ STDERR)
    logging.basicConfig(level=logging.INFO)
    download_soil_type()
