#!/bin/bash
#SBATCH --job-name=era5_land_climo
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --output=logs/era5_land_climo%j.out
#SBATCH --error=logs/era5_land_climo%j.err

set -euo pipefail

USAGE="Usage: sbatch baseline_data_generation_scripts/create_climo.sbatch <tp|swe> [--overwrite]"

VARNAME="${1:-}"
if [[ -z "${VARNAME}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi
shift 1

if [[ "${VARNAME}" != "tp" && "${VARNAME}" != "swe" ]]; then
  echo "VARNAME must be one of: tp. swe; other variables processed elsewhere; got '${VARNAME}'." >&2
  echo "${USAGE}" >&2
  exit 2
fi

OVERWRITE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --overwrite)
      OVERWRITE=true
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "${USAGE}" >&2
      exit 2
      ;;
  esac
  shift
done

mkdir -p logs

export HDF5_USE_FILE_LOCKING=FALSE

echo "Host: $(hostname)"
echo "Start: $(date)"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.create_doy_climo
  --var "${VARNAME}"
)
if [[ "${OVERWRITE}" == "true" ]]; then
  CMD+=(--overwrite)
fi
)

"${CMD[@]}"

echo "End: $(date)"
