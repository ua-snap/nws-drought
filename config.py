import os
from pathlib import Path

from era5_land_variable_registry import SUPPORTED_VARS, VARIABLE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent

# Destination to which the baseline reference data is downloaded
BASELINE_DATA_ROOT = Path(
    os.getenv("DROUGHT_BASELINE_ROOT") or REPO_ROOT.joinpath("baseline_data")
)
BASELINE_DATA_ROOT.mkdir(exist_ok=True, parents=True)

# directory containing climatologies and SPI/SPEI parameters
# for production runs, this var is likely set to a static dir on the file system
CLIM_DIR = Path(os.getenv("DROUGHT_CLIM_DIR") or BASELINE_DATA_ROOT)
CLIM_DIR.mkdir(exist_ok=True, parents=True)

# Destination to which the pipeline data is downloaded
RECENT_DATA_ROOT = REPO_ROOT.joinpath("recent_data")
RECENT_DATA_ROOT.mkdir(exist_ok=True, parents=True)

# results directory for all drought indices for all summary intervals
INDICES_DIR = REPO_ROOT.joinpath("drought_outputs")
INDICES_DIR.mkdir(exist_ok=True)

# lag between current date and first date of ERA5-Land data fetched by the CDS API
# daily updates are available within ~5 days of real time, so 5 is likely the minimum
DATA_LAG_TIME_DAYS = int(os.getenv("DATA_LAG_TIME_DAYS") or 6)
# the summary intervals for which to compute the drought indicators
INTERVALS = [7, 14, 30, 60, 90, 180, 365]
# the geographic bounding box of the area of interest
DL_BBOX = [72, -180, 51, -129]

# weights for combining soil moisture layers: prescribed during initial dev work by Brian B
SOIL_MOISTURE_WEIGHT_LAYER1 = 0.25
SOIL_MOISTURE_WEIGHT_LAYER2 = 0.75
# water budget must be shifted so only positive values are allowed
# in xclim implementation 1 mm is used
# in ERA5 "Classic" 2 mm avoided negative values for 180, 365-day intervals
WATER_BUDGET_OFFSET_M = 0.002


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
