#!/bin/bash
#SBATCH --job-name=era5_land_climo_dl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=1-00:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:TERM@300
#
# Builds the climatology for all variables from the DestinE Earth Data Hub
# mirror. Submit with your Earth Data Hub key in the environment (Slurm passes
# the submitting shell's environment to the job):
#   EDH_API_KEY=... sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
# If the job stops (for example at the time limit), submit it again: finished
# yearly files are checked and kept, so it continues where it stopped.
#
# Optionally restrict to one variable:
#   VARIABLE=tp sbatch baseline_data_generation_scripts/download_era5_land_climo.sbatch
# Allowed VARIABLE values: tp, pev, swe, swvl1, swvl2
#
# The time request assumes the rough ~10 hour estimate for all five variables;
# check it against the per-year times logged by a one-year run first. A second
# climatology job on the same node stops before fetching anything; the lock does
# not reach across nodes on BeeGFS, so don't run a login-node copy alongside a
# Slurm job (the two would only duplicate work, not damage files).
# If compute nodes can't reach the mirror, run the same command detached on the
# login node instead (see baseline_data_generation_scripts/README.md).

set -euo pipefail

# the baseline folder is shared with the cmip6 group: keep new files group-readable
# and group-writable
umask 007

: "${EDH_API_KEY:?Set EDH_API_KEY to your Earth Data Hub API key before submitting}"

mkdir -p logs

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "VARIABLE=${VARIABLE:-all}"

echo "Working directory: $(pwd)"

if [[ -n "${VARIABLE:-}" ]]; then
  uv run --frozen --group mirror python -m baseline_data_generation_scripts.download_era5_land_climo -v "${VARIABLE}"
else
  uv run --frozen --group mirror python -m baseline_data_generation_scripts.download_era5_land_climo
fi

echo "End: $(date)"
