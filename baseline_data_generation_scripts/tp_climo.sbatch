#!/bin/bash
#SBATCH --job-name=tp_climo
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --output=logs/tp_climo_%j.out
#SBATCH --error=logs/tp_climo_%j.err

set -euo pipefail

USAGE="Usage: sbatch tp_climo.sbatch /path/to/daily_dir"
DAILY_DIR="${1:-}"

if [[ -z "${DAILY_DIR}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}"

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data
export HDF5_USE_FILE_LOCKING=FALSE

echo "Host: $(hostname)"
echo "Start: $(date)"

TP_FILE="drought_climatology_baselines/tp_daily_utc_minus9_combined.nc"
OUTPUT_FILE="drought_climatology_baselines/era5_tp_climo_1981_2020.nc"

echo "tp: ${TP_FILE}"
echo "output: ${OUTPUT_FILE}"

CMD=(
  uv run --frozen python baseline_data_generation_scripts/create_tp_doy_climo.py
  --tp-file "${TP_FILE}"
  --output-file "${OUTPUT_FILE}"
)

"${CMD[@]}"

echo "End: $(date)"
