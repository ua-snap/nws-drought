To run the scripts that convert the hourly ERA5-Land data to daily summaries, you'll need to submit the following SLURM jobs.

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

## Volumetric Soil Water, Layer 1
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_swvl_level_1_1981_2020 baseline_data_generation_scripts/daily_swvl1_by_year_1981_2020 swvl1)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_swvl1_by_year_1981_2020 drought_climatology_baselines/swvl1_daily_utc_minus9_combined.nc swvl1
```

## Volumetric Soil Water, Layer 2
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-39 \
  baseline_data_generation_scripts/hour_2_daily.sbatch \
  baseline_data_generation_scripts/era5_hourly_swvl_level_2_1981_2020 baseline_data_generation_scripts/daily_swvl2_by_year_1981_2020 swvl2)

sbatch --dependency=afterok:${ARRAY_JOB_ID} \
  baseline_data_generation_scripts/hour_2_daily_combine.sbatch \
  baseline_data_generation_scripts/daily_swvl2_by_year_1981_2020 drought_climatology_baselines/swvl2_daily_utc_minus9_combined.nc swvl2
```

## Weighted soil moisture climatology (swvl)
After both combined layer files exist, build the day-of-year climatology used by the SMD index (``era5_daily_swvl_1981_2020.nc``):

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
