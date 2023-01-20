import os
from pathlib import Path

debug = os.getenv("NWS_DROUGHT_DEBUG", False)
DEBUG_MODE = False if (debug is False or debug == "False") else True

DATA_DIR = Path(os.getenv("NWS_DROUGHT_DATA_DIR") or "/tmp/nws_drought/")
DATA_DIR.mkdir(exist_ok=True, parents=True)

# directory containing climatologies and SPI/SPEI parameters
CLIM_DIR = Path(os.getenv("NWS_DROUGHT_CLIM_DIR"))

# directory for ERA5 downloads
DOWNLOAD_DIR = DATA_DIR.joinpath("inputs")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# final output dataset (NetCDF) of indices summarized over key intervals
INDICES_DIR = DATA_DIR.joinpath("outputs")
INDICES_DIR.mkdir(exist_ok=True)

DATA_LAG_TIME_DAYS = 8
DL_BBOX = [
    76,
    -180,
    44,
    -125,
]


def api_credentials_check():
    cds_api_prompt = "Climate Data Store API credentials were not found in your $HOME directory. Please verify and store a valid API key in a .cdsapirc file and visit https://cds.climate.copernicus.eu/api-how-to#install-the-cds-api-key for instructions."
    assert ".cdsapirc" in os.listdir(os.environ["HOME"]), cds_api_prompt
