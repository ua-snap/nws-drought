#!/bin/bash
#SBATCH --job-name=era5_land_climo_dl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=4-00:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:TERM@300
#
# Submit with a variable key, for example:
#   VARIABLE=tp sbatch baseline_data_generation_scripts/download_scripts/download_era5_land_climo.sbatch
# Optional distinct job names in the queue:
#   VARIABLE=pev sbatch --job-name=pev_era5_climo baseline_data_generation_scripts/download_scripts/download_era5_land_climo.sbatch
#
# Allowed VARIABLE values: tp, pev, swe, swvl1, swvl2

set -euo pipefail

: "${VARIABLE:?Set VARIABLE to one of: tp, pev, swe, swvl1, swvl2}"

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
cd "${REPO_DIR}"

mkdir -p logs

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "VARIABLE=${VARIABLE}"
echo "NWS_DROUGHT_DATA_DIR=$NWS_DROUGHT_DATA_DIR"
echo "NWS_DROUGHT_CLIM_DIR=$NWS_DROUGHT_CLIM_DIR"

uv run --frozen python -m baseline_data_generation_scripts.download_scripts.download_era5_land_climo -v "${VARIABLE}"

echo "End: $(date)"
