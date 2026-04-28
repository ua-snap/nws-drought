#!/bin/bash
#SBATCH --job-name=process_calib_params
#SBATCH --partition=t2small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=144G
#SBATCH --time=02:00:00
#SBATCH --output=logs/process_calibration_params_%A_%a.out
#SBATCH --error=logs/process_calibration_params_%A_%a.err

set -euo pipefail

USAGE="Usage:
  sbatch --array=0-5%2 process_calibration_params.sbatch compute <spi|spei> /path/to/daily_dir
  sbatch --dependency=afterok:<array_job_id> process_calibration_params.sbatch merge <spi|spei> /path/to/daily_dir"
# Final output is written to ${NWS_DROUGHT_CLIM_DIR} set below; override that export to change the destination.

MODE="${1:-}"
INDEX="${2:-}"
DAILY_DIR="${3:-}"

if [[ -z "${MODE}" || -z "${INDEX}" || -z "${DAILY_DIR}" ]]; then
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

REPO_DIR="/beegfs/CMIP6/cparr4/repos/nws-drought"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "${LOG_DIR}"

export NWS_DROUGHT_DATA_DIR=/beegfs/CMIP6/cparr4/repos/drought_data
export NWS_DROUGHT_CLIM_DIR=/beegfs/CMIP6/cparr4/repos/nws-drought/input_climos/drought_clim_data
export HDF5_USE_FILE_LOCKING=FALSE
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

if [[ ! -d "${DAILY_DIR}" ]]; then
  echo "Daily directory does not exist: ${DAILY_DIR}" >&2
  exit 1
fi

DAILY_ABS="$(readlink -f "${DAILY_DIR}")"

cd "${REPO_DIR}"

INTERVALS=(7 30 60 90 180 365)
PARTIAL_DIR="${NWS_DROUGHT_CLIM_DIR}/${INDEX}_gamma_parameter_intervals"
OUT_PATH="${NWS_DROUGHT_CLIM_DIR}/${INDEX}_gamma_parameters.nc"
mkdir -p "${NWS_DROUGHT_CLIM_DIR}"

echo "Host: $(hostname)"
echo "Start: $(date)"
echo "Mode: ${MODE}"
echo "Index: ${INDEX}"
echo "Daily dir (inputs): ${DAILY_ABS}"
echo "Partial dir: ${PARTIAL_DIR}"
echo "Output NetCDF: ${OUT_PATH}"

if [[ "${MODE}" == "compute" ]]; then
  if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
    echo "compute mode must be submitted as an array job, e.g. --array=0-5%2" >&2
    exit 2
  fi

  if ((SLURM_ARRAY_TASK_ID < 0 || SLURM_ARRAY_TASK_ID >= ${#INTERVALS[@]})); then
    echo "SLURM_ARRAY_TASK_ID must be between 0 and 5; got ${SLURM_ARRAY_TASK_ID}." >&2
    exit 2
  fi

  INTERVAL="${INTERVALS[${SLURM_ARRAY_TASK_ID}]}"
  PARTIAL_OUT="${PARTIAL_DIR}/${INDEX}_gamma_parameters_interval_$(printf "%03d" "${INTERVAL}").nc"

  echo "Array task: ${SLURM_ARRAY_TASK_ID}"
  echo "Interval: ${INTERVAL}"
  echo "Partial output: ${PARTIAL_OUT}"

  mkdir -p "${PARTIAL_DIR}"

  uv run --frozen python baseline_data_generation_scripts/process_calibration_params.py compute \
    -i "${INDEX}" \
    -d "${DAILY_ABS}" \
    --interval "${INTERVAL}" \
    -o "${PARTIAL_OUT}"

  if [[ -f "${PARTIAL_OUT}" ]]; then
    echo "Wrote ${PARTIAL_OUT}"
  else
    echo "Error: expected partial output not found at ${PARTIAL_OUT}" >&2
    exit 1
  fi
else
  uv run --frozen python baseline_data_generation_scripts/process_calibration_params.py merge \
    -i "${INDEX}" \
    --partial-dir "${PARTIAL_DIR}" \
    -o "${OUT_PATH}"

  if [[ -f "${OUT_PATH}" ]]; then
    echo "Wrote ${OUT_PATH}"
  else
    echo "Error: expected output not found at ${OUT_PATH}" >&2
    exit 1
  fi
fi

echo "End: $(date)"
