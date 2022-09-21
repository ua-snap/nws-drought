# NWS Drought Indicators

## Set Up
### Python Environment
We'll use `conda` as the umbrella environment for Python. To create the Python environment for the first time, run the following command after cloning this repository:

`conda env create -f environment.yml`

and then activate the environment with

`conda activate drought-indicators`

Development note: if you need to add a package to the environment, refresh the `environment.yml` file this way:

`conda env export | grep -v "^prefix: " > environment.yml`

### Climate Data Store (CDS) API Credentials

Complete the following items.

 - Register for the [Climate Data Store API](https://cds.climate.copernicus.eu/api-how-to).
 - Copy your credentials from the black box in the link above to a file called `.cdsapirc` in your `$HOME` directory.
 - Make sure you have accepted the [Terms and Conditions](https://cds.climate.copernicus.eu/cdsapp/#!/terms/licence-to-use-copernicus-products).


### Configuration

Visit `scripts/config.py` to...

 - Control the lag between the present date and the first date of data fetched by the CDS API

## Usage

Setup the download directory by setting a path variable:

`export NWS_DROUGHT_DOWNLOAD_DIR=/path/to/writable/location`

This path must be writable by the user executing the script.  If no path is specified, the tool defaults to `/tmp/nws_drought/`.  Downloads are removed before each run.

### Download Data

`cd scripts`

`python download.py`

## Testing + Development

Set the application debug mode with `EXPORT NWS_DROUGHT_DEBUG=True`.  Debug mode bypasses the downloads.  

If you are testing the download functionality, I recommend constraining the `area` like so:

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
