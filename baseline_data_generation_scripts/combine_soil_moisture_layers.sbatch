#!/bin/bash
#SBATCH --job-name=combine_swvl_clim
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --output=logs/combine_soil_moisture_layers_%j.out
#SBATCH --error=logs/combine_soil_moisture_layers_%j.err

set -euo pipefail

USAGE="Usage: sbatch combine_soil_moisture_layers.sbatch"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      echo "${USAGE}" >&2
      exit 0
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

SWVL1_FILE="drought_climatology_baselines/swvl1_daily_utc_minus9_combined.nc"
SWVL2_FILE="drought_climatology_baselines/swvl2_daily_utc_minus9_combined.nc"
OUTPUT_FILE="drought_climatology_baselines/era5_daily_swvl_1981_2020.nc"

echo "swvl1: ${SWVL1_FILE}"
echo "swvl2: ${SWVL2_FILE}"
echo "output: ${OUTPUT_FILE}"

CMD=(
  uv run --frozen python baseline_data_generation_scripts/combine_soil_moisture_layers.py
  --swvl1-file "${SWVL1_FILE}"
  --swvl2-file "${SWVL2_FILE}"
  --output-file "${OUTPUT_FILE}"
)

"${CMD[@]}"

echo "End: $(date)"
