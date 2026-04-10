#!/bin/bash
#SBATCH --job-name=grib2nc
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=logs/grib2nc_%A_%a.out
#SBATCH --error=logs/grib2nc_%A_%a.err

set -euo pipefail

INPUT_DIR="${1:?Usage: sbatch ... grib_to_nc_array.sbatch /path/to/input_dir [output_root]}"
OUTPUT_ROOT="${2:-}"

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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

CMD=(
    python
    "${SCRIPT_DIR}/grib_dir_to_netcdf.py"
    --input-dir "${INPUT_DIR}"
    --index "${SLURM_ARRAY_TASK_ID}"
    --verbose
)

if [[ -n "${OUTPUT_ROOT}" ]]; then
    CMD+=(--output-root "${OUTPUT_ROOT}")
fi

echo "Task ${SLURM_ARRAY_TASK_ID} on ${HOSTNAME}"
echo "Input dir: ${INPUT_DIR}"
"${CMD[@]}"