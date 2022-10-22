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

Complete the following items.

 - Register for the [Climate Data Store API](https://cds.climate.copernicus.eu/api-how-to).
 - Copy your credentials from the black box in the link above to a file called `.cdsapirc` in your `$HOME` directory.
 - Make sure you have accepted the [Terms and Conditions](https://cds.climate.copernicus.eu/cdsapp/#!/terms/licence-to-use-copernicus-products).


### Configuration

If needed, edit `./config.py` to...

 - Control the lag between the present date and the first date of data fetched by the CDS API

## Usage

### Environment variables

The follwing environment variables need to be set/modified prior to starting a Jupyter server or running any scripts:

Add the project directory to the `PYTHONPATH`, i.e. `export PYTHONPATH=$PYTHONPATH:$(pwd)`

Setup the download directory by setting a path variable:

`export NWS_DROUGHT_DOWNLOAD_DIR=/path/to/writable/location`

This path must be writable by the user executing the script.  If no path is specified, the tool defaults to `/tmp/nws_drought/`.  Downloads are removed before each run.

Store the directory containing the ERA5 climatology files:

`export NWS_DROUGHT_INPUTS_DIR=/path/to/climatologies`


### Download Data

`cd scripts`

`python download.py`

## Data sources

Data is sourced from the Climate Data Store.

The ERA5 hourly and monthly data are delayed by three months, so the [ERA5T near-real-time preliminary dataset](https://confluence.ecmwf.int/display/CUSF/ERA5+CDS+requests+which+return+a+mixture+of+ERA5+and+ERA5T+data) is used to fill in data up until five days from the current date.

## Testing + Development

*TBD pending finalizing the environment default install* You may want to install `jupyter` within the Conda environment to use the files in the `notebooks/` directory for interactive work with these scripts.  To do so, `conda install jupyter notebook`.

Set the PYTHONPATH to include the root project, i.e. `export PYTHONPATH=$PYTHONPATH:/full/path/to/this/directory`

Set the application debug mode with `export NWS_DROUGHT_DEBUG=True` (or disable it with `unset NWS_DROUGHT_DEBUG` or use `export NWS_DROUGHT_DEBUG=False`).  Debug mode bypasses the downloads.

If you are testing the download functionality, consider constraining the `area` like so:

```
 "area": [
    45,
    -180,
    44,
    -179,
 ]
```

The full bounding box is 

```
 "area": [
    76,
    -180,
    44,
    -125,
 ]
```

### Updating dependencies


Development note: if you need to add a package to the environment, refresh the `environment.yml` file this way:

`conda env export --no-builds | grep -v "^prefix: " > environment.yml`

