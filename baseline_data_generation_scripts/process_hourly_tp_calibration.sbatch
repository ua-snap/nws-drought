#!/bin/bash
#SBATCH --job-name=drought_tp_cal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --output=/beegfs/CMIP6/cparr4/repos/nws-drought/logs/%x-%j.out
#SBATCH --error=/beegfs/CMIP6/cparr4/repos/nws-drought/logs/%x-%j.err

set -euo pipefail

MAMBA_EXE="/import/home/cparr4/bin/micromamba"
REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
LOG_DIR="${REPO_DIR}/logs"
VARNAME="tp"
HOURLY_DIR="/beegfs/CMIP6/cparr4/repos/drought_data/era5_hourly_tp_1981_2020"

mkdir -p "${LOG_DIR}"

export PYTHONPATH="${REPO_DIR}"
export NWS_DROUGHT_DATA_DIR="/beegfs/CMIP6/cparr4/repos/drought_data"
export NWS_DROUGHT_CLIM_DIR="${REPO_DIR}/input_climos/drought_clim_data"

# Prevent thread oversubscription under Dask workers
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-unset}"
echo "VARNAME=${VARNAME}"
echo "HOURLY_DIR=${HOURLY_DIR}"

cd "${REPO_DIR}"

"$MAMBA_EXE" run -n drought-indicators python --version
"$MAMBA_EXE" run -n drought-indicators python \
    /beegfs/CMIP6/cparr4/repos/nws-drought/scripts/snap/process_hourly_calibration_data.py \
    -v "${VARNAME}" \
    -d "${HOURLY_DIR}"

echo "End: $(date)"