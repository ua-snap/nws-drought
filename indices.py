"""Module to assist with computing some of the indices.

"""

from xclim.indices.stats import dist_method, fit


def standardized_precipitation_index(pr, params):
    r"""Standardized Precipitation Index (SPI). 
    Adapted from xclim.indices._agro.standardized_precipitation_index to accept pre-fit gamma parameters.
    Computes the SPI for all intervals in params
    
    Args:
        pr (xarray.DataArray): recent precip data
        params (xarray.DataArray): gamma parameters fit to precip data from 1981-2020, with intervals as a dimension

    """
    # subset params to the most recent doy
    recent_doy = pr.time.dt.dayofyear[-1]
    params = params.sel(dayofyear=[recent_doy]).load()
    
    # Resampling precipitations
    pr = pr.mean(dim="time", keep_attrs=True)

    # ppf to cdf
    # ensure params has this attr set
    params.attrs["scipy_dist"] = "gamma"
    prob_pos = dist_method("cdf", params, pr.where(pr > 0))
    prob_zero = (pr == 0).astype(int) / pr.notnull().astype(int) 
    prob = prob_zero + (1 - prob_zero) * prob_pos

    # Invert to normal distribution with ppf and obtain SPI
    params_norm = xarray.DataArray(
        [0, 1],
        dims=["dparams"],
        coords=dict(dparams=(["loc", "scale"])),
        attrs=dict(scipy_dist="norm"),
    )
    spi = dist_method("ppf", params_norm, prob)
    spi.attrs["units"] = ""
    spi.attrs["calibration_period"] = "1981-2020"

    return spi