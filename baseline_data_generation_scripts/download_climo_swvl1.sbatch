#!/bin/bash
#SBATCH --job-name=swvl1_era5_land_climo_download
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

mkdir -p logs

MAMBA_EXE="/import/home/cparr4/bin/micromamba"

export PYTHONPATH=/beegfs/CMIP6/cparr4/repos/nws-drought
export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data

echo "Host: $(hostname)"
echo "Start: $(date)"

echo "PYTHONPATH=$PYTHONPATH"
echo "NWS_DROUGHT_DATA_DIR=$NWS_DROUGHT_DATA_DIR"
echo "NWS_DROUGHT_CLIM_DIR=$NWS_DROUGHT_CLIM_DIR"

"$MAMBA_EXE" run -n drought-indicators python --version
"$MAMBA_EXE" run -n drought-indicators python /beegfs/CMIP6/cparr4/repos/nws-drought/baseline_data_generation_scripts/download_swvl_level_1.py

echo "End: $(date)"