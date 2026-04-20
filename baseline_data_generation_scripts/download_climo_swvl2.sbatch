#!/bin/bash
#SBATCH --job-name=swvl2_era5_land_climo_download
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=4-00:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:TERM@300

set -euo pipefail

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
cd "${REPO_DIR}"

mkdir -p logs

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "NWS_DROUGHT_DATA_DIR=$NWS_DROUGHT_DATA_DIR"
echo "NWS_DROUGHT_CLIM_DIR=$NWS_DROUGHT_CLIM_DIR"

uv run --frozen python -m baseline_data_generation_scripts.download_swvl_level_2

echo "End: $(date)"