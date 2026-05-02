"""Single source of truth for ERA5-Land variables (CDS, GRIB, climatology paths, daily stats)."""

VARIABLE_REGISTRY = {
    "tp": {
        "cds_variable": "total_precipitation",
        "prefix": "total_precipitation_daily_",
        "climatology_dir": "era5_land_daily_tp_1981_2020",
        "short_name": "tp",
        "daily_op": "sum",
        "suffix": ".grib",
        "long_name": "Daily (UTC) total precipitation",
    },
    "pev": {
        "cds_variable": "potential_evaporation",
        "prefix": "potential_evaporation_daily_",
        "climatology_dir": "era5_land_daily_pev_1981_2020",
        "short_name": "pev",
        "daily_op": "sum",
        "suffix": ".grib",
        "long_name": "Daily (UTC) total potential evaporation",
    },
    "swe": {
        "cds_variable": "snow_depth_water_equivalent",
        "prefix": "snow_water_equivalent_daily_",
        "climatology_dir": "era5_land_daily_swe_1981_2020",
        "short_name": "sd",
        "daily_op": "mean",
        "suffix": ".nc",
        "long_name": "Daily (UTC) mean snow water equivalent",
    },
    "swvl1": {
        "cds_variable": "volumetric_soil_water_layer_1",
        "prefix": "volumetric_soil_water_level_1_daily_",
        "climatology_dir": "era5_land_daily_swvl1_1981_2020",
        "short_name": "swvl1",
        "daily_op": "mean",
        "suffix": ".nc",
        "long_name": "Daily (UTC) mean volumetric soil water layer 1",
    },
    "swvl2": {
        "cds_variable": "volumetric_soil_water_layer_2",
        "prefix": "volumetric_soil_water_level_2_hourly_",
        "climatology_dir": "era5_land_daily_swvl2_1981_2020",
        "short_name": "swvl2",
        "daily_op": "mean",
        "suffix": ".nc",
        "long_name": "Daily (UTC) mean volumetric soil water layer 1",
    },
}

SUPPORTED_VARS = frozenset(VARIABLE_REGISTRY.keys())
