import os
from pathlib import Path

debug = os.getenv("NWS_DROUGHT_DEBUG", False)
DEBUG_MODE = False if (debug is False or debug == "False") else True
REPO_ROOT = Path(__file__).resolve().parent

DATA_DIR = Path(os.getenv("NWS_DROUGHT_DATA_DIR") or "/tmp/nws_drought/")
DATA_DIR.mkdir(exist_ok=True, parents=True)

# directory containing climatologies and SPI/SPEI parameters
CLIM_DIR = Path(
    os.getenv("NWS_DROUGHT_CLIM_DIR")
    or REPO_ROOT.joinpath("drought_climatology_baselines")
)
CLIM_DIR.mkdir(exist_ok=True, parents=True)

# directory for ERA5 downloads
DOWNLOAD_DIR = DATA_DIR.joinpath("inputs")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# final output dataset (NetCDF) of indices summarized over key intervals
INDICES_DIR = DATA_DIR.joinpath("outputs")
INDICES_DIR.mkdir(exist_ok=True)

# one-off script roots (download + baseline data generation)
ERA5_HOURLY_ROOT = Path(
    os.getenv("NWS_DROUGHT_ERA5_HOURLY_DIR")
    or REPO_ROOT.joinpath("baseline_data_generation_scripts")
)
ERA5_HOURLY_ROOT.mkdir(exist_ok=True, parents=True)

ERA5_DAILY_ROOT = Path(
    os.getenv("NWS_DROUGHT_ERA5_DAILY_DIR")
    or REPO_ROOT.joinpath("baseline_data_generation_scripts")
)
ERA5_DAILY_ROOT.mkdir(exist_ok=True, parents=True)

BASELINE_REF_ROOT = Path(
    os.getenv("NWS_DROUGHT_BASELINE_REF_DIR")
    or REPO_ROOT.joinpath("drought_climatology_baselines")
)
BASELINE_REF_ROOT.mkdir(exist_ok=True, parents=True)

_VAR_HOURLY_SUFFIX = {
    "tp": "era5_hourly_tp_1981_2020",
    "pev": "era5_hourly_pev_1981_2020",
    "swe": "era5_hourly_swe_1981_2020",
    "swvl1": "era5_hourly_swvl_level_1_1981_2020",
    "swvl2": "era5_hourly_swvl_level_2_1981_2020",
}

_BASELINE_CLIMO_FILES = {
    "tp": "era5_tp_climo_1981_2020.nc",
    "swe": "era5_swe_climo_1981_2020.nc",
    "swvl": "era5_swvl_climo_1981_2020.nc",
}

# control lag between current date and first date of ERA5 data fetched by the CDS API
# daily updates are available within ~5 days of real time, so 5 is likely the minimum and 8 is a conservative choice
DATA_LAG_TIME_DAYS = int(os.getenv("DATA_LAG_TIME_DAYS") or 8)
DL_BBOX = [
    76,
    -180,
    44,
    -125,
]


def api_credentials_check():
    cds_api_prompt = "Climate Data Store API credentials were not found in your $HOME directory. Please verify and store a valid API key in a .cdsapirc file and visit https://cds.climate.copernicus.eu/api-how-to#install-the-cds-api-key for instructions."
    assert ".cdsapirc" in os.listdir(os.environ["HOME"]), cds_api_prompt


def _require_supported_var(varname: str) -> None:
    if varname not in _VAR_HOURLY_SUFFIX:
        raise ValueError(
            f"Unsupported variable {varname!r}; expected one of {sorted(_VAR_HOURLY_SUFFIX)}"
        )


def _require_supported_index(index: str) -> None:
    if index not in {"spi", "spei"}:
        raise ValueError(f"Unsupported index {index!r}; expected 'spi' or 'spei'")


def hourly_dir_for_var(varname: str) -> Path:
    _require_supported_var(varname)
    return ERA5_HOURLY_ROOT.joinpath(_VAR_HOURLY_SUFFIX[varname])


def daily_year_dir_for_var(varname: str) -> Path:
    _require_supported_var(varname)
    return ERA5_DAILY_ROOT.joinpath(f"daily_{varname}_by_year_1981_2020")


def daily_combined_file_for_var(varname: str) -> Path:
    _require_supported_var(varname)
    return ERA5_DAILY_ROOT.joinpath(f"{varname}_daily_utc_minus9_combined.nc")


def baseline_climo_file(kind: str) -> Path:
    if kind not in _BASELINE_CLIMO_FILES:
        raise ValueError(
            f"Unsupported climatology kind {kind!r}; expected one of {sorted(_BASELINE_CLIMO_FILES)}"
        )
    return BASELINE_REF_ROOT.joinpath(_BASELINE_CLIMO_FILES[kind])


def gamma_partial_dir_for_index(index: str) -> Path:
    _require_supported_index(index)
    return ERA5_DAILY_ROOT.joinpath(f"{index}_gamma_parameter_intervals")


def gamma_output_file_for_index(index: str) -> Path:
    _require_supported_index(index)
    return BASELINE_REF_ROOT.joinpath(f"{index}_gamma_parameters.nc")
