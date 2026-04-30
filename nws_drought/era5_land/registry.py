"""Single source of truth for ERA5-Land variables (CDS, GRIB, climatology paths, daily stats)."""

VARIABLE_REGISTRY = {
    "tp": {
        "cds_variable": "total_precipitation",
        "hourly_prefix": "total_precipitation_hourly_",
        "climatology_dir": "era5_hourly_tp_1981_2020",
        "grib_short_name": "tp",
        "daily_op": "sum",
        "long_name": "Daily total precipitation for UTC-9 local-day window",
    },
    "pev": {
        "cds_variable": "potential_evaporation",
        "hourly_prefix": "potential_evaporation_hourly_",
        "climatology_dir": "era5_hourly_pev_1981_2020",
        "grib_short_name": "pev",
        "daily_op": "sum",
        "long_name": "Daily total potential evaporation for UTC-9 local-day window",
    },
    "swe": {
        "cds_variable": "snow_depth_water_equivalent",
        "hourly_prefix": "snow_water_equivalent_hourly_",
        "climatology_dir": "era5_hourly_swe_1981_2020",
        "grib_short_name": "sd",
        "daily_op": "mean",
        "long_name": "Daily mean snow water equivalent for UTC-9 local-day window",
    },
    "swvl1": {
        "cds_variable": "volumetric_soil_water_layer_1",
        "hourly_prefix": "volumetric_soil_water_level_1_hourly_",
        "climatology_dir": "era5_hourly_swvl_level_1_1981_2020",
        "grib_short_name": "swvl1",
        "daily_op": "mean",
        "long_name": "Daily mean volumetric soil water layer 1 for UTC-9 local-day window",
    },
    "swvl2": {
        "cds_variable": "volumetric_soil_water_layer_2",
        "hourly_prefix": "volumetric_soil_water_level_2_hourly_",
        "climatology_dir": "era5_hourly_swvl_level_2_1981_2020",
        "grib_short_name": "swvl2",
        "daily_op": "mean",
        "long_name": "Daily mean volumetric soil water layer 2 for UTC-9 local-day window",
    },
}

SUPPORTED_VARS = frozenset(VARIABLE_REGISTRY.keys())
