# NWS Drought Indicators

## Set Up
### Python Environment
We'll use `conda` as the umbrella environment for Python. To create the Python environment for the first time, run the following command after cloning this repository:

`conda env create -f environment.yml`

and then activate the environment with

`conda activate drought-indicators`

if you add a package to the environment, refresh the `environment.yml` file:

`conda env export | grep -v "^prefix: " > environment.yml`

### Climate Data Store (CDS) API Credentials
Complete the following items.
 - Register for the [Climate Data Store API](https://cds.climate.copernicus.eu/api-how-to).
 - Copy your credentials from the black box in the link above to a file called `.cdsapirc` in your `$HOME` directory.
 - Make sure you have accepted the [Terms and Conditions](https://cds.climate.copernicus.eu/cdsapp/#!/terms/licence-to-use-copernicus-products).


 ### Configuration
Visit `scripts/config.py` to...
 - Set up test "mock" data downloads
 - Control the lag between the present date and the first date of data fetched by the CDS API

 ## Usage
 The current working assumptions is that scripts are ran from within the `scripts` directory.

 ### Download Data
`cd scripts`

`python download.py`

 A `download.log` file will be written to the scripts directory.

 ## Testing + Development
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
