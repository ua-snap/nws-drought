# NWS Drought Indicators

## Set Up

### Python Environment

We'll use `conda` as the umbrella environment for Python. To create the Python environment for the first time, run the following command after cloning this repository:

```
cd /path/to/this/repository
conda env create -f environment.yml
conda activate drought-indicators
```

### Climate Data Store (CDS) API Credentials

Complete the following items to set up permissions for downloading ERA5 data.

 - Register for the [Climate Data Store API](https://cds.climate.copernicus.eu/api-how-to).
 - Copy your credentials from the black box in the link above to a file called `.cdsapirc` in your `$HOME` directory.
 - Make sure you have accepted the [Terms and Conditions](https://cds.climate.copernicus.eu/cdsapp/#!/terms/licence-to-use-copernicus-products).

### Configuration

If needed, edit `./config.py` to...

 - Control the lag between the present date and the first date of data fetched by the CDS API
 
### Input data

Unzip the `nws_data.zip` archive file somewhere and make note of this path. This folder contains some data (climatologies) that is necessary for computing the indices.

## Usage

### Environment variables

The follwing environment variables need to be set/modified prior to running any of the code herein, such as starting a Jupyter server or running any scripts:

Add the project directory to the `PYTHONPATH`, i.e. `export PYTHONPATH=$PYTHONPATH:$(pwd)`

Setup the directory for data work (downloads, outputs, etc) by setting a path variable:

`export NWS_DROUGHT_DATA_DIR=/path/to/writable/location`

This path must be writable by the user executing the script.  If no path is specified, the tool defaults to `/tmp/nws_drought/`.  Downloads are removed before each run.

Store the directory created from extracting the `nws_data.zip` file above in `NWS_DROUGHT_CLIM_DIR`:

`export NWS_DROUGHT_CLIM_DIR=/path/to/climatologies_and_inputs`

### Download Data

You may now start downloading the hourly ERA5 data that will be used for computing the indices over the recent intervals of time. Simply run the download script:

```
cd scripts
python download.py
```

Downloads will be placed in `NWS_DROUGHT_DATA_DIR/inputs`.

### Run the processing script

Now simply run the processing script to generate the indices dataset:

`python process.py`

The new datasets - one for each interval, containing results across the grid for all indices - will be written to the `$NWS_DROUGHT_DATA_DIR/outputs` directory, with files named as such: `nws_drought_indices_<interval>day.nc`

## Data sources

Data is sourced from the Climate Data Store.

The ERA5 hourly and monthly data are delayed by three months, so the [ERA5T near-real-time preliminary dataset](https://confluence.ecmwf.int/display/CUSF/ERA5+CDS+requests+which+return+a+mixture+of+ERA5+and+ERA5T+data) is used to fill in data up until five days from the current date.

