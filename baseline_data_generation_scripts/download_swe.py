"""Download hourly ERA5-Land SWE data for computing a climatology.

Usage:
    python download_swe.py
"""

import logging
from pathlib import Path
import cdsapi
from config import (
    api_credentials_check,
    DL_BBOX,
)

api_credentials_check()


def download_swe_data(download_dir):
    """Download ERA5-Land SWE for the climatology period of 1981-2020"""
    client = cdsapi.Client()
    for year in range(1981, 2021):
        logging.info(f"Downloading ERA5-Land SWE data for {year} to {download_dir}")

        request = {
            "variable": "snow_depth_water_equivalent",
            "year": str(year),
            "month": [str(month).zfill(2) for month in range(1, 13)],
            "day": [str(day).zfill(2) for day in range(1, 32)],
            "time": [
                "00:00",
                "01:00",
                "02:00",
                "03:00",
                "04:00",
                "05:00",
                "06:00",
                "07:00",
                "08:00",
                "09:00",
                "10:00",
                "11:00",
                "12:00",
                "13:00",
                "14:00",
                "15:00",
                "16:00",
                "17:00",
                "18:00",
                "19:00",
                "20:00",
                "21:00",
                "22:00",
                "23:00",
            ],
            "data_format": "grib",
            "download_format": "unarchived",
            "area": DL_BBOX,
        }
        dst = download_dir.joinpath(f"snow_water_equivalent_hourly_{year}.grib")
        client.retrieve("reanalysis-era5-land", request, target=dst)
    return


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_dir = Path(f"era5_hourly_swe_1981_2020")
    download_dir.mkdir(exist_ok=True)
    download_swe_data(download_dir)
