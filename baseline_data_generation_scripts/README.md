## Baseline Reference Data

The bulk of the data downloaded here are used to construct a set of "baseline reference" data: climatologies and statistical distribution parameters against which the recent conditions may be compared to understand whether or not drought conditions are present with respect to climate normals, i.e. baselines. Constructing these climatologies / computing these parameters requires a few steps.

### Download the ERA5-Land Climatology
One job builds every variable for 1981–2020 from the DestinE Earth Data Hub copy of ERA5-Land (a Zarr store), not from CDS, so there is no CDS queue to wait in. It writes one netCDF file per variable per year to each variable's climatology directory, rebuilding daily values the way the CDS requests did: the 00:00 UTC value of the next day for precipitation and potential evaporation, and the mean of the 00, 06, 12 and 18 UTC values for snow water equivalent and the two soil-moisture layers. Every daily value is labeled by the day it measures, so a precipitation or evaporation total for December 31, 2020 is read from January 1, 2021 but labeled 2020-12-31; no 2021 files are written. The recurring precipitation and evaporation files are relabeled the same way when the indices are computed, so the indices' reference date is the day before the analysis date. The grid matches the recurring CDS downloads point for point.

Values differ from CDS by small amounts that grow with magnitude; the store keeps roughly 12 significant bits. Over January–March 2000 the typical and largest absolute differences were 0.00003 mm and 0.03 mm for precipitation, 0.000007 mm and 0.03 mm for potential evaporation, 0.011 mm and 3.9 mm for snow water equivalent (the largest on an 8.7 m snowpack, 0.045%), and 0.00003 and 0.00024 m³/m³ for soil moisture. These differences are accepted.

The job needs a free Earth Data Hub API key in `EDH_API_KEY` and the optional `mirror` dependency group (the sbatch script runs with it). Slurm passes the submitting shell's environment to the job:

```sh
EDH_API_KEY=... sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
```

Set `VARIABLE=<key>` to restrict it to one variable. A year whose file already holds the expected variable and dates is skipped, so if the job stops, submit it again and it continues where it stopped. The log gives each variable-year's time and the total time. Before the first full rebuild, time one year of every variable and check that the full 40 years fit the job's time request:

```sh
EDH_API_KEY=... uv run --frozen --group mirror python -m baseline_data_generation_scripts.download_era5_land_climo \
  --start-year 2000 --end-year 2000
```

If compute nodes can't reach the mirror, run the same command detached on the login node, which needs no Slurm time limit. Don't run it while a Slurm climatology job is running: the lock that stops a second run doesn't reach across nodes, so both would download the same years (each writes to its own temporary file, so neither damages the other's files):

```sh
EDH_API_KEY=... nohup setsid uv run --frozen --group mirror python -m baseline_data_generation_scripts.download_era5_land_climo \
  > logs/era5_land_climo_dl.log 2>&1 &
```

The yearly files go to the baseline folder (`/beegfs/CMIP6/snapdata/drought_reanalysis_baseline` unless `DROUGHT_BASELINE_ROOT` says otherwise). After the rebuild, rebuild the combined daily files by passing `--overwrite` to `combine_annual_files.sbatch` (next section), since an existing combined file is otherwise kept. The combine step refuses, leaving any existing combined file in place, until every year from 1981 through 2020 is present and holds every day.

### Construct Single Daily File
Merge each year of daily data into one combined daily NetCDF. Launch these jobs from the root directory of the repo.

#### Total Precipitation
```sh
sbatch baseline_data_generation_scripts/combine_annual_files.sbatch tp
```
#### Total Potential Evaporation
```sh
sbatch baseline_data_generation_scripts/combine_annual_files.sbatch pev
```
#### Snow Water Equivalent
```sh
sbatch baseline_data_generation_scripts/combine_annual_files.sbatch swe
```
#### Volumetric Soil Water, Layer 1
```sh
sbatch baseline_data_generation_scripts/combine_annual_files.sbatch swvl1
```
#### Volumetric Soil Water, Layer 2
```sh
sbatch baseline_data_generation_scripts/combine_annual_files.sbatch swvl2
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
