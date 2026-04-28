#!/bin/bash
#SBATCH --job-name=hour2day
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=logs/hour2day_%A_%a.out
#SBATCH --error=logs/hour2day_%A_%a.err

set -euo pipefail

USAGE="Usage: sbatch --array=0-N baseline_data_generation_scripts/hour_2_daily.sbatch <tp|pev|swe|swvl1|swvl2> [--overwrite]"

VARNAME="${1:-}"
OVERWRITE_FLAG="${2:-}"

if [[ -z "${VARNAME}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi

if [[ "${VARNAME}" != "tp" && "${VARNAME}" != "pev" && "${VARNAME}" != "swe" && "${VARNAME}" != "swvl1" && "${VARNAME}" != "swvl2" ]]; then
  echo "VARNAME must be one of: tp, pev, swe, swvl1, swvl2; got '${VARNAME}'." >&2
  echo "${USAGE}" >&2
  exit 2
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
export HDF5_USE_FILE_LOCKING=FALSE
cd "${REPO_DIR}"

INPUT_DIR="$(
  uv run --frozen python -c "from config import hourly_dir_for_var; print(hourly_dir_for_var('${VARNAME}'))"
)"
OUTPUT_DIR="$(
  uv run --frozen python -c "from config import daily_year_dir_for_var; print(daily_year_dir_for_var('${VARNAME}'))"
)"
mkdir -p "${OUTPUT_DIR}"

TASK_ID="${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required for array jobs}"
case "${VARNAME}" in
  tp)
    PREFIX="total_precipitation_hourly_"
    ;;
  pev)
    PREFIX="potential_evaporation_hourly_"
    ;;
  swe)
    PREFIX="snow_water_equivalent_hourly_"
    ;;
  swvl1)
    PREFIX="volumetric_soil_water_level_1_hourly_"
    ;;
  swvl2)
    PREFIX="volumetric_soil_water_level_2_hourly_"
    ;;
esac

mapfile -t YEARS < <(
  uv run --frozen python - "${INPUT_DIR}" "${PREFIX}" <<'PY'
from pathlib import Path
import re
import sys

input_dir = Path(sys.argv[1])
prefix = sys.argv[2]
pattern = re.compile(rf"^{re.escape(prefix)}(\d{{4}})\.grib$")
years = []
for path in input_dir.glob(f"{prefix}*.grib"):
    m = pattern.match(path.name)
    if m:
        years.append(int(m.group(1)))
for year in sorted(set(years)):
    # 2021 GRIB exists only to pad the last UTC-9 day of 2020; do not run annual build.
    if year != 2021:
        print(year)
PY
)

if [[ "${#YEARS[@]}" -eq 0 ]]; then
  echo "No matching yearly GRIB files found in ${INPUT_DIR} for ${VARNAME}." >&2
  exit 1
fi

if (( TASK_ID < 0 || TASK_ID >= ${#YEARS[@]} )); then
  echo "Array task ${TASK_ID} exceeds discovered year count ${#YEARS[@]}; exiting."
  exit 0
fi
YEAR="${YEARS[$TASK_ID]}"

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Array task: ${TASK_ID}"
echo "Year: ${YEAR}"
echo "Variable: ${VARNAME}"
echo "Input dir: ${INPUT_DIR}"
echo "Output dir: ${OUTPUT_DIR}"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.hourly_to_daily
  --var "${VARNAME}"
  --year "${YEAR}"
)
if [[ "${OVERWRITE_FLAG}" == "--overwrite" ]]; then
  CMD+=(--overwrite)
fi

"${CMD[@]}"

echo "End: $(date)"
