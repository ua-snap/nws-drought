#!/bin/bash
#SBATCH --job-name=tp_climo
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --output=logs/tp_climo_%j.out
#SBATCH --error=logs/tp_climo_%j.err

set -euo pipefail

USAGE="Usage: sbatch baseline_data_generation_scripts/tp_climo.sbatch"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}"

export HDF5_USE_FILE_LOCKING=FALSE

echo "Host: $(hostname)"
echo "Start: $(date)"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.create_tp_doy_climo
)

"${CMD[@]}"

echo "End: $(date)"
