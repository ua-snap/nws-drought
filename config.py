import os
from pathlib import Path

debug = os.getenv("NWS_DROUGHT_DEBUG", False)
DEBUG_MODE = False if (debug is False or debug == "False") else True
dl_loc = os.getenv("NWS_DROUGHT_DOWNLOAD_DIR", False)
DOWNLOAD_DIR = Path(dl_loc if dl_loc is not False else "/tmp/nws_drought/")
input_loc = os.getenv("NWS_DROUGHT_INPUTS_DIR", False)
INPUT_DIR = Path(input_loc if input_loc is not False else os.getcwd())

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