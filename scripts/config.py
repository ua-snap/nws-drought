import os
from pathlib import Path

MOCK_DOWNLOAD = False
DATA_LAG_TIME_DAYS = 8


def api_credentials_check():
    cds_api_prompt = "Climate Data Store API credentials were not found in your $HOME directory. Please verify and store a valid API key in a .cdsapirc file and visit https://cds.climate.copernicus.eu/api-how-to#install-the-cds-api-key for instructions."
    assert ".cdsapirc" in os.listdir(os.environ["HOME"]), cds_api_prompt
