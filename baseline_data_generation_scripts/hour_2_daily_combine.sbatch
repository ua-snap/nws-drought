#!/bin/bash
#SBATCH --job-name=hour2day_combine
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/hour2day_combine_%j.out
#SBATCH --error=logs/hour2day_combine_%j.err

set -euo pipefail

USAGE="Usage: sbatch hour_2_daily_combine.sbatch /path/to/annual_dir /path/to/output_file <tp|pev|swe|swvl1|swvl2> [--overwrite]"

ANNUAL_DIR="${1:-}"
OUTPUT_FILE="${2:-}"
VARNAME="${3:-}"
if [[ -z "${ANNUAL_DIR}" || -z "${OUTPUT_FILE}" || -z "${VARNAME}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi
shift 3

if [[ "${VARNAME}" != "tp" && "${VARNAME}" != "pev" && "${VARNAME}" != "swe" && "${VARNAME}" != "swvl1" && "${VARNAME}" != "swvl2" ]]; then
  echo "VARNAME must be one of: tp, pev, swe, swvl1, swvl2; got '${VARNAME}'." >&2
  echo "${USAGE}" >&2
  exit 2
fi

OVERWRITE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --overwrite)
      OVERWRITE=true
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "${USAGE}" >&2
      exit 2
      ;;
  esac
  shift
done

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}"

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data
export HDF5_USE_FILE_LOCKING=FALSE

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Annual dir: ${ANNUAL_DIR}"
echo "Output file: ${OUTPUT_FILE}"
echo "Variable: ${VARNAME}"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.combine_hourly_to_daily_years
  --annual-dir "${ANNUAL_DIR}"
  --output-file "${OUTPUT_FILE}"
  --var "${VARNAME}"
)
if [[ "${OVERWRITE}" == "true" ]]; then
  CMD+=(--overwrite)
fi

"${CMD[@]}"

echo "End: $(date)"
