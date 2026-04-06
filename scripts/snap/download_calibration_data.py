"""Download the daily summary ERA5-Land data for calibration in SPI and SPEI.

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
    c = cdsapi.Client()
    for year in range(1981, 2021):
        for month in [str(month).zfill(2) for month in range(1, 13)]:
            logging.info(
                f"Downloading ERA5-Land {long_name} data for {month}-{year} to {download_dir}"
            )
            c.retrieve(
                "derived-era5-single-levels-daily-statistics",
                {
                    "product_type": "reanalysis",
                    "variable": long_name,
                    "year": str(year),
                    "month": month,
                    "day": [str(day).zfill(2) for day in range(1, 32)],
                    "area": DL_BBOX,
                    "daily_statistic": "daily_sum",
                    "time_zone": "utc+00:00",
                    "frequency": "1_hourly",
                    "data_format": "netcdf",
                },
                download_dir.joinpath(f"{long_name}_daily_{year}_{month}.nc"),
            )

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
    download_dir = Path(f"era5_daily_{varname}_1981_2020")
    download_dir.mkdir(exist_ok=True)
    download_calibration_data(long_name, download_dir)
