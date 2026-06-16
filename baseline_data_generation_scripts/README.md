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

### Combine the Soil Moisture Layers and Construct the Day-of-Year Climatology.
The soil moisture layers are combined into a weighted, single representation of soil moisture that is eventually referenced by the soil moisture deficit (SMD) drought indicator.

```sh
sbatch baseline_data_generation_scripts/combine_soil_moisture_layers.sbatch
```

### Construct Total Precipitation and SWE Day-of-Year Climatologies
Convert the daily time series of data into a DOY climatology.

```sh
sbatch baseline_data_generation_scripts/create_doy_climo.sbatch <swe|tp>
```

### Determine Distribution Parameters
SPEI and SPI require computing reference distribution parameters. For each of SPI and SPEI, the parameters are computed for all summary intervals (7 day, 30 day, etc.) and then the data for each of those intervals is merged into a single file.

#### SPI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-6 baseline_data_generation_scripts/process_calibration_params.sbatch compute spi)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spi
```

#### SPEI
```sh
ARRAY_JOB_ID=$(sbatch --parsable --array=0-6 baseline_data_generation_scripts/process_calibration_params.sbatch compute spei)

sbatch --dependency=afterok:${ARRAY_JOB_ID} baseline_data_generation_scripts/process_calibration_params.sbatch merge spei
```

### Ultimate File Listing for Baseline Reference Data

Once all the above processing is complete, the set of files should look like this:
```
era5_land_tp_climo_1981_2020.nc
era5_land_swe_climo_1981_2020.nc
era5_land_swvl_climo_1981_2020.nc
spei_{SPEI_DIST}_parameters.nc
spi_{SPI_DIST}_parameters.nc
```
