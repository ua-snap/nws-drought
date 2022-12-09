"""Derive estimates of parameters of gamma distributions fit to daily precip and water budget (pr - pet) data for use in SPI and SPEI indices. Accepts a variable name argument for which dataset to process, either spi or spei.

Usage: 
    python process_calibration_params.py -v spi
    python process_calibration_params.py -v spei
Note: this script is designed to be run from within the parent directory of the daily pr and pet from the climatology period. 
"""

import argparse
import time
from multiprocessing import Pool
import xarray as xr
import xclim.indices as xci
from xclim.indices.stats import fit


def estimate_params(da, window):
    """Run the parameter estimation. Includes summarizing the data to a moving average before estimating the parameters of a gamma distribution along the time axis (year, essentially) for each day of the year.
    
    Args:
        da (xarray.DataArray): daily values, either precip or water budget, for all years in the climatology period. 
        window (int): number of days over which to compute moving averages, i.e. the "time scale" of SPI algorithm. 
    
    Returns:
        params (xarray.DataArray): parameter estimates computed over the time dimension for each day of the year in da
    """
    # computing rolling means
    roll_da = da.rolling(time=window).mean(skipna=False, keep_attrs=True)
    # estimate parameters of gamma distribution fit to yearly values for each day of the year
    params = roll_da.groupby("time.dayofyear").map(lambda x: fit(x, "gamma", "APP"))
    params = params.assign_coords(interval=window).expand_dims(interval=1)
    
    return params


def run_estimation(args):
    """Wrapper for Pool-ing the estimte_params function. 
    
    Args:
        args (list): list of tuples of arguments mathing the args for estimate_params function
        
    Returns: 
        params_ds (xarray.Dataset): gamma parameter estimates, stored in "params" data variable
    """
    print((
        "Estimating parameters of gamma distributions for"
        f" all {len(args)} intervals"
    ), end="...", flush=True)
    tic = time.perf_counter()
    with Pool(5) as pool:
        out = pool.starmap(estimate_params, args)
    ds = xr.merge(out)
    da = ds[list(ds.keys())[0]]
    da.name = "params"
    da = da.astype("float32")
    params_ds = da.to_dataset()
    print(f"done: {round((time.perf_counter() - tic) / 60)}m")
    
    return params_ds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", dest="index", type=str, help="Index name, either 'spi' or 'spei'")
    args = parser.parse_args()
    index = args.index
    
    # testing
    sel_di = {"latitude": slice(65,64), "longitude": slice(-148, -147)}
    
    # this one is getting loaded either way
    print("Reading in precip data", end="...", flush=True)
    tic = time.perf_counter()
    tp_cal_ds = xr.load_dataset("era5_daily_tp_1981_2020.nc")
#     tp_cal_ds = xr.open_dataset("era5_daily_tp_1981_2020.nc")
#     tp_cal_ds = tp_cal_ds.sel(sel_di).load()
    print(f"done, {round((time.perf_counter() - tic) / 60)}m", flush=True)
    
    # intervals (in days) to compute params over:
    intervals = [30, 60 , 90, 180, 365]
    
    if index == "spei":
        # if SPEI, we need PET data
        print("Reading in PET data", end="...", flush=True)
        tic = time.perf_counter()
        pev_cal_ds = xr.load_dataset("era5_daily_pev_1981_2020.nc")
#         pev_cal_ds = xr.open_dataset("era5_daily_pev_1981_2020.nc")
#         pev_cal_ds = pev_cal_ds.sel(sel_di).load()
        print(f"done, {round((time.perf_counter() - tic) / 60)}m", flush=True)
        
        # make water balance DataArray
        # water balance is pr - pet. pet (pev) in ERA5 is usually negative because upward fluxes are negative. So we add pet.
        wb = tp_cal_ds["tp"] + pev_cal_ds["pev"]
        wb.name = "wb"
        
        args = [(wb, window) for window in intervals]
    else:
        args = [(tp_cal_ds["tp"], window) for window in intervals]
    
    params_ds = run_estimation(args)
    print("Writing to disk")
    params_ds.to_netcdf(f"{index}_gamma_parameters.nc")
