"""This is the script that was used to download the hourly ERA5 soil moisture data for computing a climatology. A combined version of the downloaded data will be provided alongside the other climatoglogies. This is provided here for reference and should not be needed by NWS/NOAA.

Usage: 
    python download_swvl.py
"""

import logging
from pathlib import Path
import cdsapi
from config import (
    api_credentials_check,
    DL_BBOX,
)

api_credentials_check()


def download_swvl_data(download_dir):
    """Download volumetric soil water layers 1 and 2 in yearly files for the climatology period of 1981-2020"""
    for year in range(1981, 2021):
        logging.info(f"Downloading hourly ERA5 swvl data for {year} to {download_dir}")
        c = cdsapi.Client()
        c.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "format": "netcdf",
                "variable": ["volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2"],
                "year": str(year),
                "month": [str(month).zfill(2) for month in range(1, 13)],
                "day": [str(day).zfill(2) for day in range(1, 32)],
                "time": [
                    "0" + str(x) + ":00" if x <= 9 else str(x) + ":00"
                    for x in range(0, 24)
                ],
                "area": DL_BBOX,
            },
            download_dir.joinpath(f"volumetric_soil_water_hourly_{year}.nc"),
        )
    
    return

    
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_dir = Path(f"era5_hourly_swvl_1981_2020")
    download_dir.mkdir(exist_ok=True)
    download_swvl_data(download_dir)
