## Baseline Reference Data

The bulk of the data downloaded here are used to construct a set of "baseline reference" data: climatoglies and statistical distribution paramters against which current conditions may be compared to understand whether or not drought conditions may be present with respect to climate normals. Constructiing these climatologies / computing these paramters requires a few steps.

### Hourly to Daily Resample
First, the hourly ERA5-Land data (GRIB format) must be converted to daily summaries (netCDF) format. To accomplish that, submit the following SLURM jobs that process each year's worth of data individually, and then merge the each year of daily data to construct a single netCDF that encapsulates the entire time series at a daily frequency:

#### Total Precipitation
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_tp_1981_2020 baseline_data_generation_scripts/daily_tp_by_year_1981_2020 tp)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_tp_by_year_1981_2020 drought_climatology_baselines/tp_daily_utc_minus9_combined.nc tp
```

#### Total Potential Evaporation
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_pev_1981_2020 baseline_data_generation_scripts/daily_pev_by_year_1981_2020 pev)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_pev_by_year_1981_2020 drought_climatology_baselines/pev_daily_utc_minus9_combined.nc pev
```

#### Snow Water Equivalent
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_swe_1981_2020 baseline_data_generation_scripts/daily_swe_by_year_1981_2020 swe)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_swe_by_year_1981_2020 drought_climatology_baselines/swe_daily_utc_minus9_combined.nc swe
```

#### Volumetric Soil Water, Layer 1
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_swvl_level_1_1981_2020 baseline_data_generation_scripts/daily_swvl1_by_year_1981_2020 swvl1)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_swvl1_by_year_1981_2020 drought_climatology_baselines/swvl1_daily_utc_minus9_combined.nc swvl1
```

#### Volumetric Soil Water, Layer 2
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_swvl_level_2_1981_2020 baseline_data_generation_scripts/daily_swvl2_by_year_1981_2020 swvl2)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_swvl2_by_year_1981_2020 drought_climatology_baselines/swvl2_daily_utc_minus9_combined.nc swvl2
```

Launch these jobs from the root directory of the repo.

### Combine the Soil Moisture Layers and Construct the Day-of-Year climatology.

The soil moisture layers are combined into a single representation of soil moisture that is eventually referenced by the soil moisture deficit (SMD) drought indicator.

```sh
uv run --frozen python baseline_data_generation_scripts/combine_soil_moisture_layers.py \
  --swvl1-file drought_climatology_baselines/swvl1_daily_utc_minus9_combined.nc \
  --swvl2-file drought_climatology_baselines/swvl2_daily_utc_minus9_combined.nc \
  --output-file drought_climatology_baselines/era5_daily_swvl_1981_2020.nc
```
the above incantation is pre-baked into this SLURM submission script:
```sh
sbatch baseline_data_generation_scripts/combine_soil_moisture_layers.sbatch
```

### Construct Precipitation and SWE Day-of-Year Climatologies 

These convert the daily time series of data into a DOY climatology.

#### Precipitation
```sh
sbatch baseline_data_generation_scripts/tp_climo.sbatch drought_climatology_baselines/
```
#### SWE
```sh
sbatch baseline_data_generation_scripts/swe_climo.sbatch drought_climatology_baselines/
```

### Determine Distribution Parameters

SPEI and SPI require computing reference distribution parameters. For each of these indicies, the parameters is computed for several intervals (7 day, 30 day, etc.) and then the information for each of those windows is merged into a single file.

#### SPI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-5 baseline_data_generation_scripts/process_calibration_params.sbatch compute spi drought_climatology_baselines)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spi drought_climatology_baselines
```

#### SPEI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-5 baseline_data_generation_scripts/process_calibration_params.sbatch compute spei drought_climatology_baselines)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spei drought_climatology_baselines
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
