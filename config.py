import os
from pathlib import Path

from era5_land_variable_registry import SUPPORTED_VARS, VARIABLE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent

# Destination to which the baseline reference data is downloaded
BASELINE_DATA_ROOT = Path(
    os.getenv("NWS_DROUGHT_BASELINE_ROOT") or REPO_ROOT.joinpath("baseline_data")
)
BASELINE_DATA_ROOT.mkdir(exist_ok=True, parents=True)

# directory containing climatologies and SPI/SPEI parameters
# for production runs, this var is likely set to a static dir on the file system
CLIM_DIR = Path(os.getenv("NWS_DROUGHT_CLIM_DIR") or BASELINE_DATA_ROOT)
CLIM_DIR.mkdir(exist_ok=True, parents=True)

# Destination to which the pipeline data is downloaded
RECENT_DATA_ROOT = Path(
    os.getenv("NWS_DROUGHT_BASELINE_ROOT") or REPO_ROOT.joinpath("recent_data")
)
RECENT_DATA_ROOT.mkdir(exist_ok=True, parents=True)

# results directory for all drought indices for all summaryy intervals
INDICES_DIR = REPO_ROOT.joinpath("drought_outputs")
INDICES_DIR.mkdir(exist_ok=True)

#######
# control lag between current date and first date of ERA5 data fetched by the CDS API
# daily updates are available within ~5 days of real time, so 5 is likely the minimum and 8 is a conservative choice
DATA_LAG_TIME_DAYS = int(os.getenv("DATA_LAG_TIME_DAYS") or 6)
# DL_BBOX = [
#     76,
#     -180,
#     44,
#     -125,
# ]
DL_BBOX = [
    65.1,
    -147.1,
    65,
    -147,
]
INTERVALS = [7, 30, 60, 90, 180, 365]


# functions to generate the baseline data directory structures
def daily_year_dir_for_var(varname: str) -> Path:
    _require_supported_var(varname)
    return BASELINE_DATA_ROOT.joinpath(
        f"{VARIABLE_REGISTRY[varname]['climatology_dir']}"
    )


def daily_combined_file_for_var(varname: str) -> Path:
    _require_supported_var(varname)
    return BASELINE_DATA_ROOT.joinpath(f"{varname}_daily_1981_2020_combined.nc")


def climo_file_for_var(varname: str) -> Path:
    return BASELINE_DATA_ROOT.joinpath(f"era5_land_{varname}_climo_1981_2020.nc")


def gamma_partial_dir_for_index(index: str) -> Path:
    _require_supported_index(index)
    return BASELINE_DATA_ROOT.joinpath(f"{index}_gamma_parameter_intervals")


def gamma_output_file_for_index(index: str) -> Path:
    _require_supported_index(index)
    return BASELINE_DATA_ROOT.joinpath(f"{index}_gamma_parameters.nc")


# validators
def _require_supported_var(varname: str) -> None:
    if varname not in SUPPORTED_VARS:
        raise ValueError(
            f"Unsupported variable {varname!r}; expected one of {SUPPORTED_VARS}"
        )


def _require_supported_index(index: str) -> None:
    if index not in {"spi", "spei"}:
        raise ValueError(f"Unsupported index {index!r}; expected 'spi' or 'spei'")
