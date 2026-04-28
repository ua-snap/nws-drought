#!/bin/bash
#SBATCH --job-name=swe_climo
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --output=logs/swe_climo_%j.out
#SBATCH --error=logs/swe_climo_%j.err

set -euo pipefail

USAGE="Usage: sbatch swe_climo.sbatch /path/to/daily_dir"
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

SWE_FILE="drought_climatology_baselines/swe_daily_utc_minus9_combined.nc"
OUTPUT_FILE="drought_climatology_baselines/era5_swe_climo_1981_2020.nc"

echo "swe: ${SWE_FILE}"
echo "output: ${OUTPUT_FILE}"

CMD=(
  uv run --frozen python baseline_data_generation_scripts/create_swe_doy_climo.py
  --swe-file "${SWE_FILE}"
  --output-file "${OUTPUT_FILE}"
)

"${CMD[@]}"

echo "End: $(date)"
