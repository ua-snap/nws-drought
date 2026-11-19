## Baseline Reference Data

The bulk of the data downloaded here are used to construct a set of "baseline reference" data: climatologies and statistical distribution parameters against which the recent conditions may be compared to understand whether or not drought conditions are present with respect to climate normals, i.e. baselines. Constructing these climatologies / computing these parameters requires a few steps.

### Download the ERA5-Land Climatology
One job downloads every variable for 1981–2021, one CDS request at a time, with precipitation and potential evaporation combined into one request per year. Snow water equivalent and the two soil-moisture layers are requested one variable per year, because CDS refuses all three over a whole year ("cost limits exceeded"):

```sh
sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
```

Set `VARIABLE=<key>` to restrict it to one variable. A year whose files already hold the expected variable and dates is skipped. If the job hits its time limit, submit it again: it continues where it stopped and picks up any request still queued at CDS. Do not run it while the recurring download (`pipeline_download.py`) is running; see the main README.

#### Request-size benchmark
`benchmark_request_shapes.py` compares yearly and monthly requests over two rounds (a sample year, then the following year, so the second round can't be served from the CDS cache). It writes `request_shape_benchmark.md`. The climatology job keeps yearly requests unless monthly requests win both rounds.

```sh
uv run --frozen python -m baseline_data_generation_scripts.benchmark_request_shapes --year 2000
```

#### Cloud mirror comparison
`compare_era5_land_mirror.py` checks whether the DestinE Earth Data Hub copy of ERA5-Land reproduces the CDS climatology values for one sample year, and writes `mirror_comparison.md`. It makes no CDS requests. It needs a free Earth Data Hub API key in `EDH_API_KEY` and the optional `mirror` dependency group:

```sh
EDH_API_KEY=... uv run --group mirror python -m baseline_data_generation_scripts.compare_era5_land_mirror --year 2000
```

The climatology keeps coming from CDS unless every value matches exactly.

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
