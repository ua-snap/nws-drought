"""Shared ERA5-Land variable metadata for climatology and backfill downloads."""

VARIABLE_REGISTRY = {
    "tp": {
        "cds_variable": "total_precipitation",
        "hourly_prefix": "total_precipitation_hourly_",
        "climatology_dir": "era5_hourly_tp_1981_2020",
    },
    "pev": {
        "cds_variable": "potential_evaporation",
        "hourly_prefix": "potential_evaporation_hourly_",
        "climatology_dir": "era5_hourly_pev_1981_2020",
    },
    "swe": {
        "cds_variable": "snow_depth_water_equivalent",
        "hourly_prefix": "snow_water_equivalent_hourly_",
        "climatology_dir": "era5_hourly_swe_1981_2020",
    },
    "swvl1": {
        "cds_variable": "volumetric_soil_water_layer_1",
        "hourly_prefix": "volumetric_soil_water_level_1_hourly_",
        "climatology_dir": "era5_hourly_swvl_level_1_1981_2020",
    },
    "swvl2": {
        "cds_variable": "volumetric_soil_water_layer_2",
        "hourly_prefix": "volumetric_soil_water_level_2_hourly_",
        "climatology_dir": "era5_hourly_swvl_level_2_1981_2020",
    },
}
