"""Download hourly ERA5-Land data required for SPI and SPEI calibration.

Usage:
    python download_calibration_data.py -v pev
    python download_calibration_data.py -v tp
"""

import argparse
import logging
from pathlib import Path
import cdsapi
from config import (
    api_credentials_check,
    DL_BBOX,
)

api_credentials_check()

long_name_lu = {"pev": "potential_evaporation", "tp": "total_precipitation"}


def download_calibration_data(long_name, download_dir):
    """Download ERA5-Land for the climatology period of 1981-2020"""
    client = cdsapi.Client()
    for year in range(1981, 2021):
        logging.info(f"Downloading ERA5-Land {long_name_lu[long_name]} data for {year} to {download_dir}")

        request = {
            "variable": long_name,
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
        dst = download_dir.joinpath(f"{long_name}_hourly_{year}.grib")
        client.retrieve("reanalysis-era5-land", request, target=dst)
    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-v", dest="varname", type=str, help="Variable name, either 'tp' or 'pev'"
    )
    args = parser.parse_args()
    varname = args.varname
    long_name = long_name_lu[varname]
    logging.basicConfig(level=logging.INFO)
    download_dir = Path(f"era5_hourly_{varname}_1981_2020")
    download_dir.mkdir(exist_ok=True)
    download_calibration_data(long_name, download_dir)
