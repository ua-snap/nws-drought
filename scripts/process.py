"""The main processing script. This script will compute the drought indices from the downloads and other precomputed inputs.
"""

import logging
import time
import numpy as np
import pandas as pd
import xarray as xr
import xclim.indices as xci
from config import DOWNLOAD_DIR, INPUT_DIR, indices_fp
import luts
import indices as ic


def assemble_dataset(input_dir, varname):
    varname_prefix = luts.varname_prefix_lu[varname]
    prior_year = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_previous_year.nc"))
    current_year = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_current_year.nc"))
    current_month = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_current_month.nc"))
    
    # Just want to make sure our assumption that data with expver values of 1 and 5 are
    #  mutually exclusive and exhaustive
    assert np.all(
        np.isnan(current_year[varname].sel(expver=5)) == ~np.isnan(current_year[varname].sel(expver=1))
    )
    assert np.all(
        ~np.isnan(current_year[varname].sel(expver=5)) == np.isnan(current_year[varname].sel(expver=1))
    )
    
    # Select the data for each expver value and combine to get a complete continuous set of data:
    current_year_fix = xr.merge([
        current_year[varname].sel(expver=1).drop("expver"),
        current_year[varname].sel(expver=5).drop("expver")
    ])
    assert ~np.any(np.isnan(current_year_fix[varname]).values)
    
    # merge with other dataset since they all share the same coordinate variables now
    hourly_ds = xr.merge([
        prior_year,
        current_year_fix,
        current_month,
    ])
    # resample ohurly to daily
    if varname in ["tp", "pev"]:
        # total precip should be summed
        daily_ds = hourly_ds.resample(time="1D").sum()
    elif varname in ["sd", "swvl1", "swvl2"]:
        # TO DO : check how the daily values of these variables should be calculated from hourly
        daily_ds = hourly_ds.resample(time="1D").mean()
        
    return daily_ds


def subset_clim_interval(clim_ds, start_doy, end_doy):
    if start_doy < end_doy:
        sub_ds = clim_ds.sel(time=slice(start_doy, end_doy))
    else:
        sub_ds = xr.merge([
            clim_ds.sel(time=slice(0, end_doy)),
            clim_ds.sel(time=slice(start_doy, 366))
        ])
        
    return sub_ds


def process_total_precip():
    index = "tp"
    indices[index] = {}
    for i in intervals:
        indices[index][i] = ds[index].sel(
            time=slice(times[-(i)], times[-1])
        # convert from m to cm to match climatology
        ).sum(dim="time") * 100
    
    return


def process_total_precip_pon():
    index = "pntp"
    indices[index] = {}
    with xr.open_dataset(INPUT_DIR.joinpath("era5_daily_tp_climatology_1981_2020_leap.nc")) as tp_clim_ds:
        # need to remap longitude coordinates from [180, 360] to [-180, 0]
        tp_clim_ds = tp_clim_ds.assign_coords(longitude=(tp_clim_ds.longitude.values) - 360)
        for i in intervals:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_tp = subset_clim_interval(tp_clim_ds, start_doy, end_doy).sum(dim="time")
            indices[index][i] = np.round((indices["tp"][i] / clim_tp["tp"]) * 100, 1)
            indices[index][i].name = index
    
    return


def process_swe():
    index = "swe"
    indices[index] = {}
    for i in intervals:
        indices[index][i] = ds["sd"].sel(
            time=slice(times[-(i)], times[-1])
        ).mean(dim="time") * 100 # converts from m to cm
        indices[index][i].name = index
        
    return


def process_swe_pon():
    index = "pnswe"
    indices[index] = {}
    with xr.open_dataset(INPUT_DIR.joinpath("era5_swe_climo_81-20.nc")) as swe_clim_ds:
        # need to remap longitude coordinates from [180, 360] to [-180, 0]
        swe_clim_ds = swe_clim_ds.assign_coords(
            longitude=(swe_clim_ds.longitude.values) - 360,
            # just convert time dim to DOY days for consistency with tp
            time=np.arange(swe_clim_ds.time.shape[0]) + 1
        )
        for i in intervals:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swe = subset_clim_interval(swe_clim_ds, start_doy, end_doy).mean(dim="time")
            indices[index][i] = (indices["swe"][i] / clim_swe["swe"]) * 100
            # over the water, SWE will always be zero. This comes out as NaN in the results (the only NaNs)
            #  For now just treat this area as 100% of normal.
            indices[index][i].values[np.isnan(indices[index][i])] = 100
            indices[index][i].name = index
            
    return
            
            
def process_spi():
    index = "spi"
    indices[index] = {}
    with xr.open_dataset(INPUT_DIR.joinpath("spi_gamma_parameters.nc")) as spi_ds:
        for i in intervals:
            indices[index][i] = ic.spi(ds["tp"], spi_ds["params"], i)
            indices[index][i].name = index
    
    return


def process_spei():
    index = "spei"
    indices[index] = {}
    with xr.open_dataset(INPUT_DIR.joinpath("spei_gamma_parameters.nc")) as spei_ds:
        # add 1mm offset consistent with precomputed gammas
        wb = (ds["tp"] + ds["pev"]) + 0.001
        for i in intervals:
            indices[index][i] = ic.spi(wb, spei_ds["params"], i)
            indices[index][i].name = index
            
    return


if __name__ == "__main__":
    # start timer
    tic = time.perf_counter()
    # Log to STDOUT (+ STDERR)
    logging.basicConfig(level=logging.INFO)
    
    logging.info("Processing drought indices")
    logging.info("Assembling daily ERA5 datasets from downloaded hourly data")
    input_dir = DOWNLOAD_DIR.joinpath("inputs")
    ds = xr.combine_by_coords(
        [assemble_dataset(input_dir, varname) for varname in ["tp", "sd", "pev"]], 
        combine_attrs="drop_conflicts"
    )
    ds.to_netcdf(DOWNLOAD_DIR.joinpath("inputs/combined_daily_era5_vars.nc"))
    
    end_time = ds.time[-1]
    start_time = ds.time[-365]
    # ensure that this is indeed 365 days (time diff is nanoseconds)
    assert (end_time - start_time) / 86400E9
    
    # define some globals that will be used by all of the functions for computing indices
    ds = ds.sel(time=slice(start_time, end_time))
    intervals = [30, 60, 90, 180, 365]
    times = ds.time.values
    
    # process indices
    # create dict for writing results
    indices = {}
    # total precip
    logging.info("Processing total precip")
    process_total_precip()
    # total precip % of normal
    logging.info("Processing total precip % of normal")
    process_total_precip_pon()
    # SWE
    logging.info("Processing SWE")
    process_swe()
    # SWE % of normal
    logging.info("Processing SWE % of normal")
    process_swe_pon()
    # SPI
    logging.info("Processing SPI")
    process_spi()
    # SPEI
    logging.info("Processing SPEI")
    process_spei()
    # TO-DO: SMD
    
    
    # combine and save
    logging.info("Combining and saving as whole dataset")
    indices_ds = xr.merge([
        xr.concat(
            [indices[varname][i] for i in intervals], 
            pd.Index(intervals, name="interval")
        )
        for varname in indices
    ])
    indices_ds.to_netcdf(indices_fp)
    logging.info(f"Pipeline completed in {round((time.perf_counter() - tic) / 60)}m")
    
    