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

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}"

export HDF5_USE_FILE_LOCKING=FALSE

echo "Host: $(hostname)"
echo "Start: $(date)"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.combine_soil_moisture_layers
)

"${CMD[@]}"

echo "End: $(date)"
