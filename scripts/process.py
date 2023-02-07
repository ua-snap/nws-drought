"""The main processing script. This script will compute the drought indices from the downloads and other precomputed inputs.
"""

import logging
import time
import numpy as np
import pandas as pd
import xarray as xr
import xclim.indices as xci
from scipy.ndimage import gaussian_filter
from config import DOWNLOAD_DIR, CLIM_DIR, INDICES_DIR
import luts
import indices as ic


def assemble_hourly_dataset(input_dir, varname):
    """Assemble the three components of a yearly dataset into one"""
    logging.info(f"Assembling hourly dataset of {varname} data")
    varname_prefix = luts.varname_prefix_lu[varname]
    prior_year = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_previous_year.nc"))
    current_month = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_current_month.nc"))

    try:
        # The majority of analysis date cases (not january)
        current_year = xr.open_dataset(input_dir.joinpath(f"{varname_prefix}_current_year.nc"))

        # Validate assumption that data with expver values of 1 or 5 are mutually exclusive and exhaustive
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
        data_to_merge = [prior_year, current_year_fix, current_month]
    except:
        # The minority of analysis date cases (in january)
        data_to_merge = [prior_year, current_month]
        # current_month data should all have the same expver
    
    # merge datasets since they all share the same coordinate variables now
    hourly_ds = xr.merge(data_to_merge)
    return hourly_ds


def assemble_dataset(input_dir, varname):
    """Assemble a dataset by variable name"""
    
    if varname in ["tp", "pev", "sd"]:
        hourly_ds = assemble_hourly_dataset(input_dir, varname)
           
        if varname in ["tp", "pev"]:
            daily_ds = hourly_ds.resample(time="1D").sum()
        else:
            daily_ds = hourly_ds.resample(time="1D").mean()
    else:
        swvl1 = assemble_hourly_dataset(input_dir, "swvl1")
        swvl2 = assemble_hourly_dataset(input_dir, "swvl2")

        daily_da = ((swvl1["swvl1"] * 0.25) + (swvl2["swvl2"] * 0.75)).resample(
            time="1D"
        ).mean()
        daily_da.name = "swvl"
        daily_ds = daily_da.to_dataset()
        
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
        indices[index][i] = np.round(indices[index][i], 1)
    
    return


def process_total_precip_pon():
    index = "pntp"
    indices[index] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("era5_daily_tp_climatology_1981_2020_leap.nc")) as tp_clim_ds:
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
    # special case for SWE - 1 day
    # copy dataarray structure for spot to put data that will result from smoothing
    temp_da = ds["sd"].copy(deep=True) 
    # smooth with gaussian, returns same array shape but smooths
    #  0 axis only (because sigma set to 0 for other two dimensions)
    temp_da.data = gaussian_filter(temp_da, sigma=(2, 0, 0))
    # and take the most recent day
    indices[index][1] = temp_da.sel(
        time=ds.time.values[-1]
    ).drop_vars("time") * 100
    indices[index][1].name = index
    
    for i in intervals:
        indices[index][i] = ds["sd"].sel(
            time=slice(times[-(i)], times[-1])
        ).mean(dim="time") * 100 # converts from m to cm
        indices[index][i].name = index
    # round
    for i in intervals + [1]:
        indices[index][i] = np.round(indices[index][i], 1)
        
    return


def process_swe_pon():
    index = "pnswe"
    indices[index] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("era5_swe_climo_81-20.nc")) as swe_clim_ds:
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
            # don't need to multiply by 100 because swe index is in cm,
            #  so conversion of clim swe to cm would cancel with conversion of result to percentage
            #  e.g. (swe_in_cm / (clim_swe_in_m * 100)) * 100 == swe_in_cm / clim_swe_in_m
            indices[index][i] = np.round(indices["swe"][i] / clim_swe["swe"], 1)
            # over the water, SWE will always be zero. This comes out as NaN in the results (the only NaNs)
            #  For now just treat this area as 100% of normal.
            indices[index][i].values[np.isnan(indices[index][i])] = 100
            indices[index][i].name = index
            
    return
            
            
def process_spi():
    index = "spi"
    indices[index] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("spi_gamma_parameters.nc")) as spi_ds:
        for i in intervals:
            indices[index][i] = ic.spi(ds["tp"], spi_ds["params"], i)
            indices[index][i].name = index
            indices[index][i] = np.round(indices[index][i], 1)
            
    return


def process_spei():
    index = "spei"
    indices[index] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("spei_gamma_parameters.nc")) as spei_ds:
        # add 1mm offset consistent with precomputed gammas
        wb = (ds["tp"] + ds["pev"]) + 0.002
        for i in intervals:
            indices[index][i] = ic.spi(wb, spei_ds["params"], i)
            indices[index][i].name = index
            indices[index][i] = np.round(indices[index][i], 1)
        
    return


def process_smd():
    index = "smd"
    indices[index] = {}
    # special case for SMD - 1 day
    # copy dataarray structure for spot to put data that will result from smoothing
    temp_da = ds["swvl"].copy(deep=True) 
    # smooth with gaussian, returns same array shape but smooths
    #  0 axis only (because sigma set to 0 for other two dimensions)
    temp_da.data = gaussian_filter(temp_da, sigma=(2, 0, 0))
    
    with xr.open_dataset(CLIM_DIR.joinpath("era5_daily_swvl_1981_2020.nc")) as swvl_clim_ds:
        # take the most recent day for the 1-day interval
        swvl_1d = temp_da.sel(time=ds.time.values[-1]).drop_vars("time")
        clim_swvl = swvl_clim_ds["swvl"].sel(
            time=ds.time.dt.dayofyear.values[-1]
        ).drop_vars("time")
        indices[index][1] = np.round(((clim_swvl - swvl_1d) / clim_swvl) * 100, 1)
        indices[index][1].name = index
        
        for i in intervals:
            swvl = ds["swvl"].sel(
                time=slice(times[-(i)], times[-1])
            ).mean(dim="time")
            
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swvl = subset_clim_interval(swvl_clim_ds, start_doy, end_doy).mean(dim="time")
            
            indices[index][i] = np.round(((clim_swvl["swvl"] - swvl) / clim_swvl["swvl"]) * 100, 1)
            indices[index][i].name = index
        
    return


def fill_1day_nan():
    """This function simply creates dataarrays of NaNs for all indices for which we are not interested in 1day values. This helps with usability / intercompatability of resulting netCDF files
    """
    for index in ["tp", "pntp", "pnswe", "spi", "spei"]:
        # copy a dataarray structure
        indices[index][1] = indices["swe"][1].copy(deep=True)
        # fill it with NaNs
        indices[index][1].data[:] = np.nan
        indices[index][1].name = index
        
    return


def mask_land_vars():
    """For some variables, there should not be any for pixels over the ocean. This is evidenced by unresonably large or small values. Use the provided ERA5 land sea mask to apply NaN to ocean pixels of swe, pnswe, and smd."""
    lsm_fp = CLIM_DIR.joinpath("land_sea_mask.nc")
    with xr.open_dataset(lsm_fp) as lsm_ds:
        # using 50% or more land to identify land pixel
        seamask = (lsm_ds["lsm"] > 0.5).isel(time=0).drop("time")
    # seamask is masking off nonland (i.e. False over seas
    for index in ["swe", "pnswe", "smd"]:
        for interval in indices[index].keys():
            indices[index][interval] = indices[index][interval].where(seamask)

    return


if __name__ == "__main__":
    # start timer
    tic = time.perf_counter()
    # Log to STDOUT (+ STDERR)
    logging.basicConfig(level=logging.INFO)
    logging.info("Processing drought indices")
    
    logging.info("Assembling daily ERA5 datasets from downloaded hourly data")
    datasets = [assemble_dataset(DOWNLOAD_DIR, varname) for varname in ["tp", "sd", "pev", "swvl"]]
    ds = xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")
    end_time = ds.time[-1]
    ref_date = pd.to_datetime(end_time.values)
    start_time = ds.time[-365]
    ds.to_netcdf(DOWNLOAD_DIR.joinpath(f"combined_daily_era5_vars_{ref_date.strftime('%Y%m%d')}.nc"))
    
    # ensure that this is indeed 365 days (time diff is nanoseconds)
    assert (end_time - start_time) / 86400E9
    
    # define some globals that will be used by all of the functions for computing indices
    ds = ds.sel(time=slice(start_time, end_time))
    intervals = [7, 30, 60, 90, 180, 365]
    times = ds.time.values
    
    # process indices
    # create dict for writing results
    # this is consumed and passed to all functions below
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
    # SMD
    logging.info("Processing SMD")
    process_smd()
    
    # add 1day NaN arrays, not ideal but simple
    fill_1day_nan()
    # mask ocean for land vars
    mask_land_vars()
    
    # combine and save
    logging.info("Combining and saving as whole dataset")
    # write a single file for each interval
    for i in [1] + intervals:
        out_ds = xr.merge([indices[varname][i] for varname in indices])

        # merging the datasets is causing inversion along latitude dim for some reason!
        #  Flip it if it's upside down (increasing lat)
        if out_ds.latitude[1] > out_ds.latitude[0]:
            out_ds = out_ds.reindex(latitude=list(reversed(out_ds.latitude)))
        
        out_ds.attrs["reference_date"] = ref_date.strftime("%Y-%m-%d")
        out_ds.to_netcdf(INDICES_DIR.joinpath(f"nws_drought_indices_{i}day.nc"))
        
    logging.info(f"Pipeline completed in {round((time.perf_counter() - tic) / 60)}m")
    
