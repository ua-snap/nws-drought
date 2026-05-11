"""Compute the drought indices from the recent data and the other precomputed inputs."""

import logging

import numpy as np
import pandas as pd
import xarray as xr
from scipy.ndimage import gaussian_filter
from xclim.indices.stats import dist_method

from config import (
    CLIM_DIR,
    INDICES_DIR,
    INTERVALS,
    RECENT_DATA_ROOT,
    SOIL_MOISTURE_WEIGHT_LAYER1,
    SOIL_MOISTURE_WEIGHT_LAYER2,
)
from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import NETCDF_ENGINE, ds_combination, setup_logging


def combine_swvl():
    swvl1_prefix = VARIABLE_REGISTRY["swvl1"]["prefix"]
    recent_swvl1_dir = RECENT_DATA_ROOT.joinpath(
        VARIABLE_REGISTRY["swvl1"]["recent_dir"]
    )
    recent_swvl1 = {
        "prev_yr": recent_swvl1_dir.joinpath(f"{swvl1_prefix}previous_year.nc"),
        "this_month": recent_swvl1_dir.joinpath(f"{swvl1_prefix}current_month.nc"),
        "this_yr": recent_swvl1_dir.joinpath(f"{swvl1_prefix}current_year.nc"),
    }
    swvl2_prefix = VARIABLE_REGISTRY["swvl2"]["prefix"]
    recent_swvl2_dir = RECENT_DATA_ROOT.joinpath(
        VARIABLE_REGISTRY["swvl2"]["recent_dir"]
    )
    recent_swvl2 = {
        "prev_yr": recent_swvl2_dir.joinpath(f"{swvl2_prefix}previous_year.nc"),
        "this_month": recent_swvl2_dir.joinpath(f"{swvl2_prefix}current_month.nc"),
        "this_yr": recent_swvl2_dir.joinpath(f"{swvl2_prefix}current_year.nc"),
    }
    out_dir = RECENT_DATA_ROOT.joinpath("era5_land_daily_swvl")
    out_dir.mkdir(exist_ok=True)
    recent_swvl_combined = {
        "prev_yr": out_dir.joinpath("swvl_previous_year.nc"),
        "this_month": out_dir.joinpath("swvl_current_month.nc"),
        "this_yr": out_dir.joinpath("swvl_current_year.nc"),
    }

    try:
        # check on data availability
        for period_of_record in recent_swvl1.keys():
            ds = xr.open_dataset(recent_swvl1[period_of_record])
            ds.close()
            recent_data_to_open = list(recent_swvl1.keys())
    except FileNotFoundError:
        # should only happen if current month is January
        recent_data_to_open = ["prev_yr", "this_month"]

    for period_of_record in recent_data_to_open:
        swvl1_da = xr.open_dataset(recent_swvl1[period_of_record])["swvl1"]
        swvl2_da = xr.open_dataset(recent_swvl2[period_of_record])["swvl2"]
        swvl1_a, swvl2_a = xr.align(swvl1_da, swvl2_da, join="inner")
        swvl = (
            swvl1_a * SOIL_MOISTURE_WEIGHT_LAYER1
            + swvl2_a * SOIL_MOISTURE_WEIGHT_LAYER2
        ).astype("float32")
        swvl.name = "swvl"
        swvl.attrs["source"] = (
            "Weighted combination of swvl1 and swvl2 UTC daily means."
        )

        out_path = recent_swvl_combined[period_of_record]
        swvl.to_netcdf(
            out_path,
            engine=NETCDF_ENGINE,
            encoding={"swvl": {"dtype": "float32"}},
        )
        logging.info(f"Wrote combined recent swvl to {out_path}")


def assemble_recent_downloads(variable_key):
    """Assemble the individual components of the recently downloaded data into a single data structure."""

    logging.info(f"Assembling dataset of {variable_key} data")

    if variable_key == "swvl":
        prefix = "swvl_"
        recent_data_dir_for_variable = RECENT_DATA_ROOT.joinpath("era5_land_daily_swvl")
        suffix = ".nc"
    else:
        prefix = VARIABLE_REGISTRY[variable_key]["prefix"]
        recent_data_dir_for_variable = RECENT_DATA_ROOT.joinpath(
            VARIABLE_REGISTRY[variable_key]["recent_dir"]
        )
        suffix = VARIABLE_REGISTRY[variable_key]["suffix"]

    recent_data = {
        "prev_yr": recent_data_dir_for_variable.joinpath(
            f"{prefix}previous_year{suffix}"
        ),
        "this_month": recent_data_dir_for_variable.joinpath(
            f"{prefix}current_month{suffix}"
        ),
        "this_yr": recent_data_dir_for_variable.joinpath(
            f"{prefix}current_year{suffix}"
        ),
    }

    try:
        # first, majority (non-January) of analysis date cases
        data_to_merge = [
            recent_data["prev_yr"],
            recent_data["this_yr"],
            recent_data["this_month"],
        ]
        logging.info(
            "Merging recent data for prior year, current year, current month..."
        )
        recent_data_ds = ds_combination(data_to_merge, suffix)
    except FileNotFoundError:
        # should only happen if current month is January
        data_to_merge = [
            recent_data["prev_yr"],
            recent_data["this_month"],
        ]
        logging.info("Merging recent data for prior year and current month...")
        recent_data_ds = ds_combination(data_to_merge, suffix)

    logging.info("Merging recent data complete.")
    return recent_data_ds


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
    indices["tp"] = {}
    for i in INTERVALS:
        indices["tp"][i] = (
            ds["tp"]
            .sel(
                valid_time=slice(times[-(i)], times[-1])
                # convert from m to cm to match climatology
            )
            .sum(dim="valid_time")
            * 100
        )
        indices["tp"][i] = np.round(indices["tp"][i], 1)
        indices["tp"][i].attrs["units"] = "cm"


def process_total_precip_pon():
    indices["pntp"] = {}
    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_land_tp_climo_1981_2020.nc")
    ) as tp_clim_ds:
        # need to remap longitude coordinates from [180, 360] to [-180, 0]
        # # CP note: do we need this???
        # tp_clim_ds = tp_clim_ds.assign_coords(
        #     longitude=(tp_clim_ds.longitude.values) - 360
        # )
        for i in INTERVALS:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_tp = subset_clim_interval(tp_clim_ds, start_doy, end_doy).sum(
                dim="time"
            )
            indices["pntp"][i] = np.round((indices["tp"][i] / clim_tp["tp"]) * 100, 1)
            indices["pntp"][i].name = "pntp"
            indices["pntp"][i].attrs["units"] = "percent"


def process_swe():
    indices["swe"] = {}
    # special case for SWE: 1 day
    # copy DataArray structure for spot to put data that will result from smoothing
    temp_da = ds["sd"].copy(deep=True)
    # smooth with gaussian, returns same array shape but smooths
    #  0 axis only (because sigma set to 0 for other two dimensions)
    temp_da.data = gaussian_filter(temp_da, sigma=(2, 0, 0))
    # and take the most recent day
    indices["swe"][1] = (
        temp_da.sel(valid_time=ds.valid_time.values[-1]).drop_vars("valid_time") * 100
    )
    indices["swe"][1].name = "swe"
    indices["swe"][1].attrs["units"] = "cm"

    for i in INTERVALS:
        indices["swe"][i] = (
            ds["sd"]
            .sel(valid_time=slice(times[-(i)], times[-1]))
            .mean(dim="valid_time")
            * 100
        )  # converts from m to cm
        indices["swe"][i].name = "swe"
        indices["swe"][i].attrs["units"] = "cm"

    for i in INTERVALS + [1]:
        indices["swe"][i] = np.round(indices["swe"][i], 1)


def process_swe_pon():
    indices["pnswe"] = {}
    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_land_swe_climo_1981_2020.nc")
    ) as swe_clim_ds:
        # need to remap longitude coordinates from [180, 360] to [-180, 0]
        swe_clim_ds = swe_clim_ds.assign_coords(
            # CP note: may not need below
            #            longitude=(swe_clim_ds.longitude.values) - 360,
            # just convert time dim to DOY days for consistency with tp
            time=np.arange(swe_clim_ds.time.shape[0]) + 1,
        )

        # special case for SWE % of normal: 1 day
        end_doy = pd.Timestamp(times[-1]).dayofyear
        clim_swe = swe_clim_ds["sd"].sel(time=end_doy)
        indices["pnswe"][1] = np.round(indices["swe"][1] / clim_swe, 1)
        indices["pnswe"][1].name = "pnswe"
        indices["pnswe"][1].attrs["units"] = "cm"

        for i in INTERVALS:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swe = subset_clim_interval(swe_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )
            # don't need to multiply by 100 because swe index is in cm,
            # so conversion of clim swe to cm would cancel with conversion of result to percentage
            # e.g. (swe_in_cm / (clim_swe_in_m * 100)) * 100 == swe_in_cm / clim_swe_in_m
            indices["pnswe"][i] = np.round(indices["swe"][i] / clim_swe["sd"], 1)
            # over the water, SWE will always be zero. This comes out as NaN in the results (the only NaNs)
            # For now just treat this area as 100% of normal.
            indices["pnswe"][i].values[np.isnan(indices["pnswe"][i])] = 100
            # CP Note: may not need abov line after transition to ERA5-Land
            indices["pnswe"][i].name = "pnswe"
            indices["pnswe"][i].attrs["units"] = "percent"


def _spi(pr: xr.DataArray, params: xr.DataArray, interval: int):
    """Computes Standardized Precipitation Index (SPI).
    Adapted from xclim.indices._agro.standardized_precipitation_index to accept pre-fit gamma parameters.

    Args:
        pr (xr.DataArray): recent precip data
        params (xr.DataArray): gamma parameters fit to precip data from 1981-2020, with intervals as a dimension
        interval (int): interval length

    Returns:
        spi (xr.DataArray): the standardized precipitation index
    """
    # subset params to the most recent doy and interval
    recent_doy = pr.valid_time.dt.dayofyear[-1]
    params = (
        params.sel(dayofyear=[recent_doy], interval=interval)
        .drop_vars("interval")
        .load()
    )

    # resampling precipitations
    pr = pr.sel(valid_time=slice(pr.valid_time[-interval], pr.valid_time[-1])).mean(
        dim="valid_time", keep_attrs=True
    )

    # ppf to cdf
    # ensure params has this attr set
    params.attrs["scipy_dist"] = "gamma"
    prob_pos = dist_method("cdf", params, pr.where(pr > 0))
    prob_zero = (pr == 0).astype(int) / pr.notnull().astype(int)
    prob = prob_zero + (1 - prob_zero) * prob_pos

    # Invert to normal distribution with ppf and obtain SPI
    params_norm = xr.DataArray(
        [0, 1],
        dims=["dparams"],
        coords=dict(dparams=(["loc", "scale"])),
        attrs=dict(scipy_dist="norm"),
    )
    spi = dist_method("ppf", params_norm, prob)
    spi.attrs["units"] = ""
    spi.attrs["calibration_period"] = "1981-2020"
    spi = spi.drop_vars("dayofyear").squeeze()

    return spi


def process_spi():
    indices["spi"] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("spi_gamma_parameters.nc")) as spi_ds:
        for i in INTERVALS:
            indices["spi"][i] = _spi(ds["tp"], spi_ds["params"], i)
            indices["spi"][i].name = "spi"
            indices["spi"][i] = np.round(indices["spi"][i], 1)
            indices["spi"][i].attrs["units"] = ""


def process_spei():
    indices["spei"] = {}
    with xr.open_dataset(CLIM_DIR.joinpath("spei_gamma_parameters.nc")) as spei_ds:
        # add 1mm (?) offset consistent with precomputed gammas
        wb = (ds["tp"] + ds["pev"]) + 0.002
        for i in INTERVALS:
            indices["spei"][i] = _spi(wb, spei_ds["params"], i)
            indices["spei"][i].name = "spei"
            indices["spei"][i] = np.round(indices["spei"][i], 1)
            indices["spei"][i].attrs["units"] = ""


def process_smd():
    indices["smd"] = {}
    # special case for SMD: a 1-day summary interval
    # copy dataarray structure for spot to put data that will result from smoothing
    temp_da = ds["swvl"].copy(deep=True)
    # smooth with gaussian, returns same array shape but smooths
    # 0 axis only (because sigma set to 0 for other two dimensions)
    temp_da.data = gaussian_filter(temp_da, sigma=(2, 0, 0))

    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_daily_swvl_1981_2020.nc")
    ) as swvl_clim_ds:
        # take the most recent day for the 1-day interval
        swvl_1d = temp_da.sel(valid_time=ds.time.values[-1]).drop_vars("valid_time")
        clim_swvl = (
            swvl_clim_ds["swvl"]
            .sel(time=ds.time.dt.dayofyear.values[-1])
            .drop_vars("time")
        )
        indices["smd"][1] = np.round(((clim_swvl - swvl_1d) / clim_swvl) * 100, 1)

        indices["smd"][1].name = "smd"
        indices["smd"][1].attrs["units"] = "percent"

        for i in INTERVALS:
            swvl = ds["swvl"].sel(time=slice(times[-(i)], times[-1])).mean(dim="time")

            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swvl = subset_clim_interval(swvl_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )

            indices["smd"][i] = np.round(
                ((clim_swvl["swvl"] - swvl) / clim_swvl["swvl"]) * 100, 1
            )
            indices["smd"][i].name = "smd"
            indices["smd"][i].attrs["units"] = "percent"


if __name__ == "__main__":
    setup_logging()
    logging.info("Processing drought indices...")

    logging.info("Combnining recent soil moisture data")
    # combine_swvl()

    logging.info("Assembling recent ERA5-Land data...")
    datasets = [
        assemble_recent_downloads(varname)
        for varname in [
            "swe",
            "swvl",
            "tp",
            "pev",
        ]
    ]

    ds = xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")
    end_time = ds.valid_time[-1]
    logging.info(f"End time for combined dataset is {end_time}.")
    ref_date = pd.to_datetime(end_time.values)
    start_time = ds.valid_time[-365]
    logging.info(f"Start time for combined dataset is {start_time}.")
    ds.to_netcdf(
        RECENT_DATA_ROOT.joinpath(
            f"combined_daily_era5_land_drought_vars_{ref_date.strftime('%Y%m%d')}.nc",
        ),
        engine=NETCDF_ENGINE,
    )

    # ensure that this is indeed 365 days (time diff is nanoseconds)
    assert (end_time - start_time) / 86400e9

    # below globals(!) are inherited by all of the functions for computing indices
    # the dataset `ds` the combined data, sliced to just include the previous year's worth of daata
    # `times` the times we want to look at
    # an initialized results dict in which to store the data
    ds = ds.sel(valid_time=slice(start_time, end_time))
    times = ds.valid_time.values
    # construct dict for processing the actual indices
    indices = {}

    logging.info("Processing drought index: total precipitation...")
    process_total_precip()

    logging.info("Processing drought index: total precipitation % of normal...")
    process_total_precip_pon()

    logging.info("Processing drought index: SWE...")
    process_swe()

    logging.info("Processing drought index: SWE % of normal...")
    process_swe_pon()

    logging.info("Processing drought index: SPI...")
    process_spi()

    logging.info("Processing drought index: SPEI...")
    process_spei()

    logging.info("Processing drought index: SMD...")
    process_smd()

    logging.info("Combining individual drought indicators and summary intervals")
    # write a single file for each interval
    for i in [1] + INTERVALS:
        if i == 1:
            out_ds = xr.merge(
                [indices[varname][i] for varname in ["swe", "pnswe", "smd"]]
            )
            out_ds = out_ds.drop_vars("time")
        else:
            out_ds = xr.merge([indices[varname][i] for varname in indices])

        #     # merging the datasets is causing inversion along latitude dim for some reason!
        #     #  Flip it if it's upside down (increasing lat)
        #     if out_ds.latitude[1] > out_ds.latitude[0]:
        #         out_ds = out_ds.reindex(latitude=list(reversed(out_ds.latitude)))

        out_ds.attrs["reference_date"] = ref_date.strftime("%Y-%m-%d")
        # remove dataset-level units attribute
        del out_ds.attrs["units"]
        out_ds.to_netcdf(INDICES_DIR.joinpath(f"drought_indices_{i}day.nc"))

    logging.info("Pipeline completed.")
