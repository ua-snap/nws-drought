"""The main processing script. This script will compute the drought indices from the downloads and other precomputed inputs."""

import logging
import time
import numpy as np
import pandas as pd
import xarray as xr
import xclim.indices as xci
from scipy.ndimage import gaussian_filter
from config import DOWNLOAD_DIR, CLIM_DIR, INDICES_DIR
from nws_drought.era5_land.grib import open_hourly_dataset
from nws_drought.era5_land.utc9 import compute_daily_utc9_from_hourly
import luts
import indices as ic

_LUT_TO_REGISTRY = {
    "tp": "tp",
    "sd": "swe",
    "pev": "pev",
    "swvl1": "swvl1",
    "swvl2": "swvl2",
}
_GRIB_SUFFIX = ".grib"


def drop_expver(ds):
    """In the case that there is an expvar variable, we want to flatten it along that dimension, because we don't care if it's from ERA5 or ERA5T

    Args:
        ds (xarray.Dataset): Dataset *with* expver dimension

    Returns:
        fix_ds (xarray.Dataset): Dataset without expver dimension
    """
    if "expver" in ds.dims:
        # Validate assumption that data with expver values of 1 or 5 are mutually exclusive and exhaustive
        assert np.all(np.isnan(ds.sel(expver=5)) == ~np.isnan(ds.sel(expver=1)))
        assert np.all(~np.isnan(ds.sel(expver=5)) == np.isnan(ds.sel(expver=1)))

        fix_ds = xr.merge(
            [ds.sel(expver=1).drop("expver"), ds.sel(expver=5).drop("expver")]
        )
        # should be no NaNs
        varname = list(ds.data_vars)[0]
        assert ~np.any(np.isnan(fix_ds[varname]).values)
    else:
        # i.e., do nothing to the dataset
        fix_ds = ds

    return fix_ds


def assemble_hourly_grib_chunks(input_dir, lut_varname):
    """Concatenate pipeline GRIB chunks (previous year, optional current year, current month)."""
    logging.info("Assembling hourly GRIB chunks for %s", lut_varname)
    stem = luts.varname_prefix_lu[lut_varname]
    reg_key = _LUT_TO_REGISTRY[lut_varname]
    paths = [
        input_dir.joinpath(f"{stem}_previous_year{_GRIB_SUFFIX}"),
    ]
    cy_path = input_dir.joinpath(f"{stem}_current_year{_GRIB_SUFFIX}")
    if cy_path.is_file():
        paths.append(cy_path)
    paths.append(input_dir.joinpath(f"{stem}_current_month{_GRIB_SUFFIX}"))

    hourly_parts = [open_hourly_dataset(p, varname=reg_key) for p in paths]
    hourly_ds = xr.concat(hourly_parts, dim="valid_time")
    hourly_ds = hourly_ds.sortby("valid_time")
    return drop_expver(hourly_ds)


def assemble_dataset(input_dir, varname):
    """Assemble daily ERA5-Land fields (UTC-9 logic shared with baseline hourly_to_daily)."""

    if varname in ["tp", "pev", "sd"]:
        hourly_ds = assemble_hourly_grib_chunks(input_dir, varname)
        try:
            daily_ds = compute_daily_utc9_from_hourly(
                hourly_ds, _LUT_TO_REGISTRY[varname]
            )
        finally:
            hourly_ds.close()
        if varname == "sd":
            daily_ds = daily_ds.rename({"swe": "sd"})
        return daily_ds

    swvl1_hourly = assemble_hourly_grib_chunks(input_dir, "swvl1")
    swvl2_hourly = assemble_hourly_grib_chunks(input_dir, "swvl2")
    try:
        swvl1_daily = compute_daily_utc9_from_hourly(swvl1_hourly, "swvl1")
        swvl2_daily = compute_daily_utc9_from_hourly(swvl2_hourly, "swvl2")
    finally:
        swvl1_hourly.close()
        swvl2_hourly.close()

    da1, da2 = xr.align(
        swvl1_daily["swvl1"],
        swvl2_daily["swvl2"],
        join="inner",
    )
    daily_da = da1 * 0.25 + da2 * 0.75
    daily_da.name = "swvl"
    return daily_da.to_dataset()


def subset_clim_interval(clim_ds, start_doy, end_doy):
    if start_doy < end_doy:
        sub_ds = clim_ds.sel(time=slice(start_doy, end_doy))
    else:
        sub_ds = xr.merge(
            [
                clim_ds.sel(time=slice(0, end_doy)),
                clim_ds.sel(time=slice(start_doy, 366)),
            ]
        )

    return sub_ds


def process_total_precip():
    index = "tp"
    indices[index] = {}
    for i in intervals:
        indices[index][i] = (
            ds[index]
            .sel(
                time=slice(times[-(i)], times[-1])
                # convert from m to cm to match climatology
            )
            .sum(dim="time")
            * 100
        )
        indices[index][i] = np.round(indices[index][i], 1)
        indices[index][i].attrs["units"] = "cm"

    return


def process_total_precip_pon():
    index = "pntp"
    indices[index] = {}
    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_daily_tp_climatology_1981_2020_leap.nc")
    ) as tp_clim_ds:
        # need to remap longitude coordinates from [180, 360] to [-180, 0]
        tp_clim_ds = tp_clim_ds.assign_coords(
            longitude=(tp_clim_ds.longitude.values) - 360
        )
        for i in intervals:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_tp = subset_clim_interval(tp_clim_ds, start_doy, end_doy).sum(
                dim="time"
            )
            indices[index][i] = np.round((indices["tp"][i] / clim_tp["tp"]) * 100, 1)
            indices[index][i].name = index
            indices[index][i].attrs["units"] = "percent"

    return


def process_swe():
    index = "swe"
    indices[index] = {}

    # special case for SWE: 1 day
    # copy DataArray structure for spot to put data that will result from smoothing
    temp_da = ds["sd"].copy(deep=True)
    # smooth with gaussian, returns same array shape but smooths
    #  0 axis only (because sigma set to 0 for other two dimensions)
    temp_da.data = gaussian_filter(temp_da, sigma=(2, 0, 0))
    # and take the most recent day
    indices[index][1] = temp_da.sel(time=ds.time.values[-1]).drop_vars("time") * 100
    indices[index][1].name = index
    indices[index][1].attrs["units"] = "cm"

    for i in intervals:
        indices[index][i] = (
            ds["sd"].sel(time=slice(times[-(i)], times[-1])).mean(dim="time") * 100
        )  # converts from m to cm
        indices[index][i].name = index
        indices[index][i].attrs["units"] = "cm"
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
            time=np.arange(swe_clim_ds.time.shape[0]) + 1,
        )

        # special case for SWE % of normal: 1 day
        end_doy = pd.Timestamp(times[-1]).dayofyear
        clim_swe = swe_clim_ds["swe"].sel(time=end_doy)
        indices[index][1] = np.round(indices["swe"][1] / clim_swe, 1)
        indices[index][1].name = index
        indices[index][1].attrs["units"] = "cm"

        for i in intervals:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swe = subset_clim_interval(swe_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )
            # don't need to multiply by 100 because swe index is in cm,
            #  so conversion of clim swe to cm would cancel with conversion of result to percentage
            #  e.g. (swe_in_cm / (clim_swe_in_m * 100)) * 100 == swe_in_cm / clim_swe_in_m
            indices[index][i] = np.round(indices["swe"][i] / clim_swe["swe"], 1)
            # over the water, SWE will always be zero. This comes out as NaN in the results (the only NaNs)
            #  For now just treat this area as 100% of normal.
            indices[index][i].values[np.isnan(indices[index][i])] = 100
            indices[index][i].name = index
            indices[index][i].attrs["units"] = "percent"

    return


def process_spi():
    index = "spi"
    indices[index] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("spi_gamma_parameters.nc")) as spi_ds:
        for i in intervals:
            indices[index][i] = ic.spi(ds["tp"], spi_ds["params"], i)
            indices[index][i].name = index
            indices[index][i] = np.round(indices[index][i], 1)
            indices[index][i].attrs["units"] = ""

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
            indices[index][i].attrs["units"] = ""

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

    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_daily_swvl_1981_2020.nc")
    ) as swvl_clim_ds:
        # take the most recent day for the 1-day interval
        swvl_1d = temp_da.sel(time=ds.time.values[-1]).drop_vars("time")
        clim_swvl = (
            swvl_clim_ds["swvl"]
            .sel(time=ds.time.dt.dayofyear.values[-1])
            .drop_vars("time")
        )
        indices[index][1] = np.round(((clim_swvl - swvl_1d) / clim_swvl) * 100, 1)
        indices[index][1].name = index
        indices[index][1].attrs["units"] = "percent"

        for i in intervals:
            swvl = ds["swvl"].sel(time=slice(times[-(i)], times[-1])).mean(dim="time")

            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swvl = subset_clim_interval(swvl_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )

            indices[index][i] = np.round(
                ((clim_swvl["swvl"] - swvl) / clim_swvl["swvl"]) * 100, 1
            )
            indices[index][i].name = index
            indices[index][i].attrs["units"] = "percent"

    return


if __name__ == "__main__":
    # start timer
    tic = time.perf_counter()
    # Log to STDOUT (+ STDERR)
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("Processing drought indices")

    logging.info("Assembling daily ERA5 datasets from downloaded hourly data")
    datasets = [
        assemble_dataset(DOWNLOAD_DIR, varname)
        for varname in ["tp", "sd", "pev", "swvl"]
    ]
    ds = xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")
    end_time = ds.time[-1]
    ref_date = pd.to_datetime(end_time.values)
    start_time = ds.time[-365]
    ds.to_netcdf(
        DOWNLOAD_DIR.joinpath(
            f"combined_daily_era5_vars_{ref_date.strftime('%Y%m%d')}.nc"
        )
    )

    # ensure that this is indeed 365 days (time diff is nanoseconds)
    assert (end_time - start_time) / 86400e9

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

    # combine and save
    logging.info("Combining and saving as whole dataset")
    # write a single file for each interval
    for i in [1] + intervals:
        if i == 1:
            out_ds = xr.merge(
                [indices[varname][i] for varname in ["swe", "pnswe", "smd"]]
            )
            out_ds = out_ds.drop("time")
        else:
            out_ds = xr.merge([indices[varname][i] for varname in indices])

        # merging the datasets is causing inversion along latitude dim for some reason!
        #  Flip it if it's upside down (increasing lat)
        if out_ds.latitude[1] > out_ds.latitude[0]:
            out_ds = out_ds.reindex(latitude=list(reversed(out_ds.latitude)))

        out_ds.attrs["reference_date"] = ref_date.strftime("%Y-%m-%d")
        # remove units attr brought from.. first of merged dataArrays?
        del out_ds.attrs["units"]
        out_ds.to_netcdf(INDICES_DIR.joinpath(f"nws_drought_indices_{i}day.nc"))

    logging.info(f"Pipeline completed in {round((time.perf_counter() - tic) / 60)}m")
