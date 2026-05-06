## Baseline Reference Data

The bulk of the data downloaded here are used to construct a set of "baseline reference" data: climatologies and statistical distribution parameters against which the recent conditions may be compared to understand whether or not drought conditions are present with respect to climate normals, i.e. baselines. Constructing these climatologies / computing these parameters requires a few steps.

### Construct Single Daily File
Merge each year of daily data into one combined daily NetCDF. Launch these jobs from the root directory of the repo.

#### Total Precipitation
```sh
sbatch baseline_data_generation_scripts/combine_annual.sbatch tp
```
#### Total Potential Evaporation
```sh
sbatch baseline_data_generation_scripts/combine_annual.sbatch pev
```
#### Snow Water Equivalent
```sh
sbatch baseline_data_generation_scripts/combine_annual.sbatch swe
```
#### Volumetric Soil Water, Layer 1
```sh
sbatch baseline_data_generation_scripts/combine_annual.sbatch swvl1
```
#### Volumetric Soil Water, Layer 2
```sh
sbatch baseline_data_generation_scripts/combine_annual.sbatch swvl2
```

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
era5_tp_climo_1981_2020.nc
era5_swe_climo_1981_2020.nc
era5_swvl_climo_1981_2020.nc
spei_gamma_parameters.nc
spi_gamma_parameters.nc
```
