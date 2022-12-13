"""This is the script that was used to download the hourly ERA5 potential evaporation data for calibration in SPI and SPEI calcultions. A combined versions of the downloaded data will be provided alongside the other fixed inputs (e.g. climatoglogies). This is provided here for reference and should not be needed by NWS/NOAA.

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
    """Download potential evaporation for the climatology period of 1981-2020"""
    for year in range(1981, 2021):
        logging.info(f"Downloading hourly ERA5 PEV data for {year} to {download_dir}")
        c = cdsapi.Client()
        c.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "format": "netcdf",
                "variable": long_name,
                "year": str(year),
                "month": [str(month).zfill(2) for month in range(1, 13)],
                "day": [str(day).zfill(2) for day in range(1, 32)],
                "time": [
                    "0" + str(x) + ":00" if x <= 9 else str(x) + ":00"
                    for x in range(0, 24)
                ],
                "area": DL_BBOX,
            },
            download_dir.joinpath(f"{long_name}_hourly_{year}.nc"),
        )
    
    return

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", dest="varname", type=str, help="Variable name, either 'tp' or 'pev'")
    args = parser.parse_args()
    varname = args.varname
    long_name = long_name_lu[varname]
    logging.basicConfig(level=logging.INFO)
    download_dir = Path(f"era5_hourly_{varname}_1981_2020")
    download_dir.mkdir(exist_ok=True)
    download_calibration_data(long_name, download_dir)
