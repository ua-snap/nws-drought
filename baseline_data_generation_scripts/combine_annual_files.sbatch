#!/bin/bash
#SBATCH --job-name=combine_annual
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/combine_annual%j.out
#SBATCH --error=logs/combine_annual%j.err

set -euo pipefail

USAGE="Usage: sbatch baseline_data_generation_scripts/combine_annual_files.sbatch <tp|pev|swe|swvl1|swvl2> [--overwrite]"

VARNAME="${1:-}"
if [[ -z "${VARNAME}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi
shift 1

if [[ "${VARNAME}" != "tp" && "${VARNAME}" != "pev" && "${VARNAME}" != "swe" && "${VARNAME}" != "swvl1" && "${VARNAME}" != "swvl2" ]]; then
  echo "VARNAME must be one of: tp, pev, swe, swvl1, swvl2; got '${VARNAME}'." >&2
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

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}"

export HDF5_USE_FILE_LOCKING=FALSE

ANNUAL_DIR="$(
  uv run --frozen python -c "from config import daily_year_dir_for_var; print(daily_year_dir_for_var('${VARNAME}'))"
)"
OUTPUT_FILE="$(
  uv run --frozen python -c "from config import daily_combined_file_for_var; print(daily_combined_file_for_var('${VARNAME}'))"
)"

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Annual dir: ${ANNUAL_DIR}"
echo "Output file: ${OUTPUT_FILE}"
echo "Variable: ${VARNAME}"

CMD=(
  uv run --frozen python -m baseline_data_generation_scripts.combine_annual_files
  --var "${VARNAME}"
)
if [[ "${OVERWRITE}" == "true" ]]; then
  CMD+=(--overwrite)
fi

"${CMD[@]}"

echo "End: $(date)"
