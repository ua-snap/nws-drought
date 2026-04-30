"""Open ERA5-Land hourly GRIB files with cfgrib."""

from pathlib import Path

import xarray as xr

from nws_drought.era5_land.registry import VARIABLE_REGISTRY


def open_hourly_dataset(path: Path, *, varname: str) -> xr.Dataset:
    """Open one ERA5-Land GRIB file with a 1D valid_time axis.

    Args:
        path: Path to the GRIB file.
        varname: Registry key (e.g. "tp", "swe").

    Returns:
        Dataset with a single data variable named ``varname`` and sorted ``valid_time``.
    """
    ds = xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={
            "time_dims": ["valid_time"],
            "coords_as_attributes": ["surface", "number"],
            "indexpath": "",
        },
    )

    source_var = VARIABLE_REGISTRY[varname]["grib_short_name"]
    if source_var not in ds.data_vars:
        ds.close()
        raise ValueError(
            f"Expected GRIB variable {source_var!r} for registry key {varname!r} "
            f"in {path.name}, found {list(ds.data_vars)}"
        )

    out = ds[[source_var]].rename({source_var: varname}).sortby("valid_time")
    out.attrs.pop("history", None)
    return out
