"""Process the hourly soil moisture data to the daily scale for use in SMD indicator. Relies on hourly data downloaded with download_swvl.py, which fetches layers 1 and 2. Layers 1 and 2 are combined using weights of 0.25 for layer 1 and 0.75 for layer 2. 

Usage: 
    python process_hourly_swvl_data.py -d /atlas_scratch/kmredilla/nws_drought_indicators/scratch/era5_hourly_swvl_1981_2020

Note: this script is designed to be run from within the parent directory of the folders containing the hourly data files. 
"""

import argparse
import time
from pathlib import Path
import xarray as xr
from dask.diagnostics import ProgressBar
from dask.distributed import Client


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-d", dest="data_dir", type=str, help="Directory where hourly ERA5 swvl files are saved.")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    
    client = Client(n_workers=16)
    
    fps = sorted(list(data_dir.glob("*.nc")))
    ds = xr.open_mfdataset(fps, parallel=True, chunks={"time": -1})
    # weighting by layer thickness; set up compute for daily climatologies
    clim_da = ((ds["swvl1"] * 0.25) + (ds["swvl2"] * 0.75)).groupby(
        "time.dayofyear"
    ).mean(dim="time").rename({"dayofyear": "time"})
    clim_da.name = "swvl"
    
    delayed_write = clim_da.to_dataset().to_netcdf(
        f"era5_daily_swvl_1981_2020.nc",
        compute=False
    )
    with ProgressBar():
        results = delayed_write.compute()

    client.close()
