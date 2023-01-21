"""Process the hourly calibration data to the daily scale for use in SPI and SPEI indices. Accepts a variable name argument for which dataset to process. 

Usage: 
    python process_hourly_calibration_data.py -v pev
    python process_hourly_calibration_data.py -v tp
Note: this script is designed to be run from within the parent directory of the folders containing the hourly data files. 
"""

import argparse
import time
from pathlib import Path
import xarray as xr
from dask.distributed import client
from dask.diagnostics import ProgressBar


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", dest="varname", type=str, help="Variable name, either 'tp' or 'pev'")
    args = parser.parse_args()
    varname = args.varname
    
    client = Client(n_workers=16)

    # assumes running from parent of download dirs
    fps = sorted(list(Path(f"era5_hourly_{varname}_1981_2020").glob("*.nc")))
    ds = xr.open_mfdataset(fps, parallel=True, chunks={"time": -1})
    
    # assumes both pev and tp should be accumulated over a day
    new_ds = ds.resample(time="1D").sum()

    # write to disk
    print("Resampling and writing daily data to disk...", flush=True)
    delayed_write = new_ds.to_netcdf(f"era5_daily_{varname}_1981_2020.nc", compute=False)
    with ProgressBar():
        results = delayed_write.compute()
        
    client.close()
