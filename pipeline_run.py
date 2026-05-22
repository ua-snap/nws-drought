"""Compute the drought indices from the recent data and the other precomputed inputs."""

import logging

import numpy as np
import pandas as pd
import xarray as xr
from xclim.indices.stats import dist_method

from config import (
    CLIM_DIR,
    INDICES_DIR,
    INTERVALS,
    RECENT_DATA_ROOT,
    SOIL_MOISTURE_WEIGHT_LAYER1,
    SOIL_MOISTURE_WEIGHT_LAYER2,
    SPEI_DIST,
    SPI_DIST,
    WATER_BUDGET_OFFSET_M,
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


def subset_clim_interval(clim_ds: xr.Dataset, start_doy: float, end_doy: float):
    if start_doy <= end_doy:
        sub_ds = clim_ds.sel(time=slice(start_doy, end_doy))
    else:
        sub_ds = xr.concat(
            [
                clim_ds.sel(time=slice(start_doy, 366)),
                clim_ds.sel(time=slice(1, end_doy)),
            ],
            dim="time",
        )
    return sub_ds


def _standardized_index(
    values: xr.DataArray,
    params: xr.DataArray,
    interval: int,
    scipy_dist: str,
    apply_zero_precipitation_correction: bool = False,
):
    """Compute a standardized index from pre-fit statistical distribution parameters."""
    recent_doy = values.valid_time.dt.dayofyear[-1]
    params = (
        params.sel(dayofyear=[recent_doy], interval=interval)
        .drop_vars("interval")
        .load()
    )
    params.attrs["scipy_dist"] = scipy_dist

    values_i = values.sel(
        valid_time=slice(values.valid_time[-interval], values.valid_time[-1])
    ).mean(dim="valid_time", keep_attrs=True)

    if apply_zero_precipitation_correction:
        # For SPI, where the input variable is precipitation.
        # Many valid observations could be exactly 0
        # And positive precipitation amounts are continuous and likely right-skewed
        #
        # A gamma distribution is only defined for positive values, so we should not
        # pass exact-zero precipitation values into the gamma CDF. Instead, evaluate
        # the fitted distribution only where the interval precipitation is > 0.
        positive_values_only = values_i.where(values_i > 0)

        probability_from_positive_distribution = dist_method(
            "cdf",
            params,
            positive_values_only,
        )

        # Track where the original interval value was exactly zero.
        #
        # This is SPI-specific bookkeeping. A zero precipitation amount is a valid
        # climate observation, not missing data, but it cannot be evaluated directly
        # by a gamma distribution. We therefore treat zero values separately from
        # positive values.
        #
        # Keep missing input values as NaN so that true missing data still propagates
        # through the calculation.
        observed_zero_precipitation = xr.where(
            values_i.notnull(),
            (values_i == 0).astype("float32"),
            np.nan,
        )

        # Combine the zero-precipitation handling with the positive-value CDF.
        #
        # For positive precipitation values:
        #   observed_zero_precipitation = 0
        #   probability = probability_from_positive_distribution
        #
        # For zero precipitation values:
        #   observed_zero_precipitation = 1
        #   probability is handled by the zero-value branch
        #
        # This branch should NOT be used for SPEI, because SPEI is based on water
        # balance rather than precipitation. Water balance can legitimately be
        # negative, so applying `values_i > 0` would incorrectly mask valid dry
        # conditions and create artificial no-data values.
        probability = (
            observed_zero_precipitation
            + (1 - observed_zero_precipitation) * probability_from_positive_distribution
        )
    else:
        # This branch is intended for non-zero-inflated standardized indices,
        # especially SPEI.
        #
        # SPEI is based on climatic water balance, not precipitation:
        #
        #     water_balance = precipitation - PET
        #
        # In this pipeline, because `pev` is usually negative, that is computed as:
        #
        #     water_balance = tp + pev
        #
        # Unlike precipitation, water balance can legitimately be negative.
        # Negative values are not missing data; they represent dry water-balance
        # conditions where evaporative demand exceeds precipitation supply.
        #
        # Therefore, do NOT apply `values_i.where(values_i > 0)` here.
        # That positive-value mask is appropriate for gamma-based SPI, but it
        # would incorrectly remove valid negative SPEI inputs and create
        # artificial terrestrial no-data values.
        probability = dist_method(
            "cdf",
            params,
            values_i,
        )

    # Convert cumulative probabilities to standardized normal scores.
    #
    # The final SPI/SPEI value is produced by applying the inverse CDF, or PPF,
    # of the standard normal distribution to the fitted-distribution probability.
    #
    # However, norm.ppf(0) is -inf and norm.ppf(1) is +inf. Exact 0 or 1
    # probabilities can occur because of numerical precision, extreme fitted
    # tails, or values outside the effective range of the fitted distribution.
    #
    # Clipping keeps the standardized index finite while only affecting the most
    # extreme tail values.
    probability_floor = np.float32(1e-6)
    probability_ceiling = np.float32(1.0 - probability_floor)

    bounded_probability = probability.clip(
        min=probability_floor,
        max=probability_ceiling,
    )

    # Parameters for the standard normal distribution.
    #
    # The fitted drought-index distribution gives us a cumulative probability.
    # We then map that probability onto a standard normal distribution with:
    #
    #     mean = 0
    #     standard deviation = 1
    #
    # This is what turns the fitted probability into a unitless standardized
    # drought index value.
    standard_normal_parameters = xr.DataArray(
        [0, 1],
        dims=["dparams"],
        coords=dict(dparams=(["loc", "scale"])),
        attrs=dict(scipy_dist="norm"),
    )

    # Transform probability to a standardized index value.
    #
    # Negative values indicate drier-than-normal conditions.
    # Positive values indicate wetter-than-normal conditions.
    #
    # For SPI, the input probability came from the precipitation distribution.
    # For SPEI, the input probability came from the water-balance distribution.
    standardized_index = dist_method(
        "ppf",
        standard_normal_parameters,
        bounded_probability,
    )

    # The standardized index is unitless by construction.
    standardized_index.attrs["units"] = ""
    standardized_index.attrs["calibration_period"] = "1981-2020"

    # The parameter-selection step preserves singleton coordinates such as
    # `dayofyear`. Once the computation is complete, these are no longer useful
    # output dimensions/coordinates for the final map, so remove/squeeze them.
    standardized_index = standardized_index.drop_vars(
        "dayofyear",
        errors="ignore",
    ).squeeze()

    return standardized_index


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
        for i in INTERVALS:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_tp = subset_clim_interval(tp_clim_ds, start_doy, end_doy).sum(
                dim="time"
            )
            indices["pntp"][i] = xr.where(
                clim_tp["tp"] > 0,
                np.round((indices["tp"][i] / clim_tp["tp"]), 1),
                np.nan,
            )
            indices["pntp"][i].name = "pntp"
            indices["pntp"][i].attrs["units"] = "percent"


def process_swe():

    indices["swe"] = {}

    for i in INTERVALS:
        indices["swe"][i] = (
            ds["sd"]
            .sel(valid_time=slice(times[-(i)], times[-1]))
            .mean(dim="valid_time")
            * 100
        )  # convert from m to cm
        indices["swe"][i].name = "swe"
        indices["swe"][i].attrs["units"] = "cm"
        indices["swe"][i] = np.round(indices["swe"][i], 1)


def process_swe_pon():

    indices["pnswe"] = {}
    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_land_swe_climo_1981_2020.nc")
    ) as swe_clim_ds:
        swe_clim_ds = swe_clim_ds.assign_coords(
            # just convert time dim to DOY days for consistency with tp
            time=np.arange(swe_clim_ds.time.shape[0]) + 1,
        )

        for i in INTERVALS:
            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swe = subset_clim_interval(swe_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )
            # don't need to multiply by 100 because swe index is in cm,
            # so conversion of clim swe to cm would cancel with conversion of result to percentage
            # e.g. (swe_in_cm / (clim_swe_in_m * 100)) * 100 == swe_in_cm / clim_swe_in_m
            indices["pnswe"][i] = xr.where(
                clim_swe["sd"] > 0,
                np.round(indices["swe"][i] / clim_swe["sd"], 1),
                np.nan,
            )

            # over the water, SWE will always be zero. This comes out as NaN in the results (the only NaNs)
            indices["pnswe"][i].name = "pnswe"
            indices["pnswe"][i].attrs["units"] = "percent"


def _spi(pr: xr.DataArray, params: xr.DataArray, interval: int):
    """Computes Standardized Precipitation Index (SPI).
    Adapted from xclim.indices._agro.standardized_precipitation_index to accept pre-fit statistical distribution parameters.

    Args:
        pr (xr.DataArray): recent precip data
        params (xr.DataArray): statistical distribution parameters fit to precip data from 1981-2020, with intervals as a dimension
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

    # ensure params has this attr set
    # params.attrs["scipy_dist"] = SPI_DIST

    # ppf to cdf
    prob_pos = dist_method("cdf", params, pr.where(pr > 0))
    prob_zero = xr.where(pr.notnull(), (pr == 0).astype("float32"), np.nan)
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
    with xr.open_dataset(CLIM_DIR.joinpath(f"spi_{SPI_DIST}_parameters.nc")) as spi_ds:
        for i in INTERVALS:
            indices["spi"][i] = _standardized_index(
                ds["tp"],
                spi_ds["params"],
                i,
                scipy_dist=SPI_DIST,
                apply_zero_precipitation_correction=True,
            )
            indices["spi"][i].name = "spi"
            indices["spi"][i] = np.round(indices["spi"][i], 1)
            indices["spi"][i].attrs["units"] = ""


def process_spei():
    indices["spei"] = {}
    with xr.open_dataset(
        CLIM_DIR.joinpath(f"spei_{SPEI_DIST}_parameters.nc")
    ) as spei_ds:
        wb = (ds["tp"] + ds["pev"]) + WATER_BUDGET_OFFSET_M

        for i in INTERVALS:
            indices["spei"][i] = _standardized_index(
                wb,
                spei_ds["params"],
                i,
                scipy_dist=SPEI_DIST,
                apply_zero_precipitation_correction=False,
            )
            indices["spei"][i].name = "spei"
            indices["spei"][i] = np.round(indices["spei"][i], 1)
            indices["spei"][i].attrs["units"] = ""


def process_smd():

    indices["smd"] = {}

    with xr.open_dataset(
        CLIM_DIR.joinpath("era5_land_swvl_climo_1981_2020.nc")
    ) as swvl_clim_ds:
        for i in INTERVALS:
            swvl = (
                ds["swvl"]
                .sel(valid_time=slice(times[-(i)], times[-1]))
                .mean(dim="valid_time")
            )

            start_doy = pd.Timestamp(times[-i]).dayofyear
            end_doy = pd.Timestamp(times[-1]).dayofyear
            clim_swvl = subset_clim_interval(swvl_clim_ds, start_doy, end_doy).mean(
                dim="time"
            )

            indices["smd"][i] = xr.where(
                clim_swvl["swvl"] > 0,
                np.round(((clim_swvl["swvl"] - swvl) / clim_swvl["swvl"]) * 100, 1),
                np.nan,
            )
            indices["smd"][i].name = "smd"
            indices["smd"][i].attrs["units"] = "percent"


if __name__ == "__main__":
    setup_logging()
    logging.info("Processing drought indices...")

    logging.info("Combnining recent soil moisture data")
    combine_swvl()

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

    datasets = xr.align(*datasets, join="inner")
    ds = xr.merge(
        datasets,
        join="exact",
        compat="no_conflicts",
        combine_attrs="drop_conflicts",
    )
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

    # below globals(!) are inherited by all the functions that compute indices:
    #    the `ds` of the combined recent data, sliced to just include the previous year
    #    `times` the times we want to look at
    #    `indicies` an initialized results dict in which to store the data
    ds = ds.sel(valid_time=slice(start_time, end_time))
    times = ds.valid_time.values
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
    for i in INTERVALS:
        arrays = [
            indices[varname][i].drop_vars("time", errors="ignore")
            for varname in indices
        ]

        out_ds = xr.merge(
            arrays,
            join="exact",
            compat="no_conflicts",
            combine_attrs="drop_conflicts",
        )

        out_ds.attrs["reference_date"] = ref_date.strftime("%Y-%m-%d")
        out_ds.to_netcdf(
            INDICES_DIR.joinpath(
                f"drought_indices_{i}day_{ref_date.strftime('%Y_%m_%d')}.nc"
            )
        )

    logging.info("Pipeline completed.")
