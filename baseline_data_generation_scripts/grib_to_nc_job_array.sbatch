#!/bin/bash
#SBATCH --job-name=grib2nc
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:00:10
#SBATCH --output=logs/grib2nc_%A_%a.out
#SBATCH --error=logs/grib2nc_%A_%a.err

set -euo pipefail

INPUT_DIR="${1:?Usage: sbatch ... grib_to_nc_array.sbatch /path/to/input_dir [output_root]}"
OUTPUT_ROOT="${2:-}"

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
cd "${REPO_DIR}"

mkdir -p logs

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Task: ${SLURM_ARRAY_TASK_ID:-none}"
echo "Input dir: ${INPUT_DIR}"
echo "Output root: ${OUTPUT_ROOT:-<default beside input>}"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.grib_to_netcdf
  --input-dir "${INPUT_DIR}"
)
if [[ -n "${OUTPUT_ROOT}" ]]; then
  CMD+=(--output-root "${OUTPUT_ROOT}")
fi

"${CMD[@]}"

echo "End: $(date)"
