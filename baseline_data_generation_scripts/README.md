## Baseline Reference Data

The bulk of the data downloaded here are used to construct a set of "baseline reference" data: climatoglies and statistical distribution paramters against which current conditions may be compared to understand whether or not drought conditions may be present with respect to climate normals. Constructiing these climatologies / computing these paramters requires a few steps.

### Directory Configuration (three roots only)

These one-off scripts derive all input/output paths from `config.py` using three optional environment variables:

- `NWS_DROUGHT_ERA5_HOURLY_DIR`: root for hourly ERA5-Land GRIB downloads.
- `NWS_DROUGHT_ERA5_DAILY_DIR`: root for daily intermediate outputs (per-year daily files, combined daily files, and gamma interval partials).
- `NWS_DROUGHT_BASELINE_REF_DIR`: root for final baseline reference artifacts only.

When unset, defaults in `config.py` are used.

### Hourly to Daily Resample
First, the hourly ERA5-Land data (GRIB format) must be converted to daily summaries (netCDF) format. Submit the following SLURM jobs that process each year's worth of data individually, then merge each year of daily data into one combined daily NetCDF.

#### Total Precipitation
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch tp)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch tp
```

#### Total Potential Evaporation
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch pev)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch pev
```

#### Snow Water Equivalent
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch swe)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch swe
```

#### Volumetric Soil Water, Layer 1
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch swvl1)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch swvl1
```

#### Volumetric Soil Water, Layer 2
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch swvl2)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch swvl2
```

Launch these jobs from the root directory of the repo.

### Combine the Soil Moisture Layers and Construct the Day-of-Year climatology.

The soil moisture layers are combined into a single representation of soil moisture that is eventually referenced by the soil moisture deficit (SMD) drought indicator.

```sh
uv run --frozen python -m baseline_data_generation_scripts.combine_soil_moisture_layers
```
the above incantation is pre-baked into this SLURM submission script:
```sh
sbatch baseline_data_generation_scripts/combine_soil_moisture_layers.sbatch
```

### Construct Precipitation and SWE Day-of-Year Climatologies 

These convert the daily time series of data into a DOY climatology.

#### Precipitation
```sh
sbatch baseline_data_generation_scripts/tp_climo.sbatch
```
#### SWE
```sh
sbatch baseline_data_generation_scripts/swe_climo.sbatch
```

### Determine Distribution Parameters

SPEI and SPI require computing reference distribution parameters. For each of these indicies, the parameters is computed for several intervals (7 day, 30 day, etc.) and then the information for each of those windows is merged into a single file.

#### SPI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-5 baseline_data_generation_scripts/process_calibration_params.sbatch compute spi)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spi
```

#### SPEI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-5 baseline_data_generation_scripts/process_calibration_params.sbatch compute spei)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spei
```

### Ultimate File Listing for Baseline Reference Data

Once all the above processing is complete, the set of files should look like this:
```
247M era5_tp_climo_1981_2020.nc
247M era5_swe_climo_1981_2020.nc
247M era5_swvl_climo_1981_2020.nc
4.3G spei_gamma_parameters.nc
4.3G spi_gamma_parameters.nc
```
