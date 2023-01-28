"""This is the script that was used to download the hourly ERA5 land sea mask. This will be provided alongside the other data to NWS. This is provided here for reference and should not be needed by NWS/NOAA.

Usage: 
    python download_lsm.py
"""

import logging
from pathlib import Path
import cdsapi
from config import (
    api_credentials_check,
    DL_BBOX,
)

api_credentials_check()


def download_swvl_data():
    """Download volumetric soil water layers 1 and 2 in yearly files for the climatology period of 1981-2020"""

    lsm_fp = "land_sea_mask.nc"
    logging.info(f"Downloading land sea mask to {lsm_fp}")
    c = cdsapi.Client()
    c.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": "reanalysis",
            "format": "netcdf",
            "variable": ["land_sea_mask"],
            "year": "1959",
            "month": "01",
            "day": "01",
            "time": "00:00",
            "area": DL_BBOX,
        },
        lsm_fp,
    )
    
    return

    
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_swvl_data()
