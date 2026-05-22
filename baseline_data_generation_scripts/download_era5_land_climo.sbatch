#!/bin/bash
#SBATCH --job-name=era5_land_climo_dl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=4-00:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:TERM@300
#
# Submit with a variable key, for example:
#   VARIABLE=tp sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
# Optional distinct job names in the queue:
#   VARIABLE=pev sbatch --job-name=pev_era5_climo baseline_data_generation_scripts/download_era5_land_climo.sbatch
#
# Allowed VARIABLE values: tp, pev, swe, swvl1, swvl2

set -euo pipefail

: "${VARIABLE:?Set VARIABLE to one of: tp, pev, swe, swvl1, swvl2}"

mkdir -p logs

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "VARIABLE=${VARIABLE}"

echo "Working directory: $(pwd)"

uv run --frozen python -m baseline_data_generation_scripts.download_era5_land_climo -v "${VARIABLE}"

echo "End: $(date)"
