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
# Downloads the climatology for all variables, one CDS request at a time:
#   sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
# If the job stops (for example at the time limit), submit it again: finished
# yearly files are checked and kept, and a request still queued at CDS is
# picked up rather than sent again, so it continues where it stopped.
#
# Optionally restrict to one variable:
#   VARIABLE=tp sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
# Allowed VARIABLE values: tp, pev, swe, swvl1, swvl2

set -euo pipefail

mkdir -p logs

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "VARIABLE=${VARIABLE:-all}"

echo "Working directory: $(pwd)"

if [[ -n "${VARIABLE:-}" ]]; then
  uv run --frozen python -m baseline_data_generation_scripts.download_era5_land_climo -v "${VARIABLE}"
else
  uv run --frozen python -m baseline_data_generation_scripts.download_era5_land_climo
fi

echo "End: $(date)"
