#!/bin/bash
#SBATCH --job-name=calib_params
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=144G
#SBATCH --time=03:00:00
#SBATCH --output=logs/calibration_params_%A_%a.out
#SBATCH --error=logs/calibration_params_%A_%a.err

set -euo pipefail

USAGE="Usage:
  sbatch --array=0-5%2 baseline_data_generation_scripts/process_calibration_params.sbatch compute <spi|spei>
  sbatch --dependency=afterok:<array_job_id> baseline_data_generation_scripts/process_calibration_params.sbatch merge <spi|spei>"

MODE="${1:-}"
INDEX="${2:-}"

if [[ -z "${MODE}" || -z "${INDEX}" ]]; then
  echo "${USAGE}" >&2
  exit 2
fi

if [[ "${MODE}" != "compute" && "${MODE}" != "merge" ]]; then
  echo "MODE must be compute or merge; got '${MODE}'." >&2
  echo "${USAGE}" >&2
  exit 2
fi

if [[ "${INDEX}" != "spi" && "${INDEX}" != "spei" ]]; then
  echo "INDEX must be spi or spei; got '${INDEX}'." >&2
  echo "${USAGE}" >&2
  exit 2
fi

mkdir -p logs

export HDF5_USE_FILE_LOCKING=FALSE
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mapfile -t INTERVALS < <(
  uv run --frozen python -c "from config import INTERVALS; print(*INTERVALS, sep='\n')"
)

PARTIAL_DIR="$(
  uv run --frozen python -c "from config import statistical_rv_partial_dir_for_index; print(statistical_rv_partial_dir_for_index('${INDEX}'))"
)"
OUT_PATH="$(
  uv run --frozen python -c "from config import statistical_rv_output_file_for_index; print(statistical_rv_output_file_for_index('${INDEX}'))"
)"
mkdir -p "${PARTIAL_DIR}" "$(dirname "${OUT_PATH}")"

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Mode: ${MODE}"
echo "Index: ${INDEX}"
echo "Partial dir: ${PARTIAL_DIR}"
echo "Output NetCDF: ${OUT_PATH}"

if [[ "${MODE}" == "compute" ]]; then
  if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
    echo "compute mode must be submitted as an array job, e.g. --array=0-5%2" >&2
    exit 2
  fi

  INTERVAL="${INTERVALS[${SLURM_ARRAY_TASK_ID}]}"
  #PARTIAL_OUT="${PARTIAL_DIR}/${INDEX}_gamma_parameters_interval_$(printf "%03d" "${INTERVAL}").nc"

  echo "Array task: ${SLURM_ARRAY_TASK_ID}"
  echo "Interval: ${INTERVAL}"
  #echo "Partial output: ${PARTIAL_OUT}"

  mkdir -p "${PARTIAL_DIR}"

  uv run --frozen python -m baseline_data_generation_scripts.process_calibration_params compute \
    -i "${INDEX}" \
    --interval "${INTERVAL}"

  # if [[ -f "${PARTIAL_OUT}" ]]; then
  #   echo "Wrote ${PARTIAL_OUT}"
  # else
  #   echo "Error: expected partial output not found at ${PARTIAL_OUT}" >&2
  #   exit 1
  # fi
else
  uv run --frozen python -m baseline_data_generation_scripts.process_calibration_params merge \
    -i "${INDEX}"

  if [[ -f "${OUT_PATH}" ]]; then
    echo "Wrote ${OUT_PATH}"
  else
    echo "Error: expected output not found at ${OUT_PATH}" >&2
    exit 1
  fi
fi

echo "End: $(date)"
