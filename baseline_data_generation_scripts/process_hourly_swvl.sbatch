#!/bin/bash
#SBATCH --job-name=drought_swvl_climo
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/beegfs/CMIP6/cparr4/repos/nws-drought/logs/%x-%j.out
#SBATCH --error=/beegfs/CMIP6/cparr4/repos/nws-drought/logs/%x-%j.err

set -euo pipefail

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
LOG_DIR="${REPO_DIR}/logs"

LAYER1_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought/baseline_data_generation_scripts/era5_hourly_swvl_level_1_1981_2020_nc"
LAYER2_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought/baseline_data_generation_scripts/era5_hourly_swvl_level_2_1981_2020_nc"

OUT_DIR="${REPO_DIR}/drought_climatology_baselines"

mkdir -p "${LOG_DIR}"
mkdir -p "${OUT_DIR}"

export NWS_DROUGHT_DATA_DIR="/beegfs/CMIP6/cparr4/repos/drought_data"
export NWS_DROUGHT_CLIM_DIR="${REPO_DIR}/drought_climatology_baselines"
export HDF5_USE_FILE_LOCKING=FALSE

# Prevent thread oversubscription in numeric libraries.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1


echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Layer1 dir: ${LAYER1_DIR}"
echo "Layer2 dir: ${LAYER2_DIR}"
echo "Output dir: ${OUT_DIR}"

cd "${REPO_DIR}"

uv run --frozen python -m baseline_data_generation_scripts.process_hourly_swvl_data \
  -d_layer_1 "${LAYER1_DIR}" \
  -d_layer_2 "${LAYER2_DIR}"

echo "End: $(date)"