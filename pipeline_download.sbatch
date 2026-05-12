#!/bin/bash
#SBATCH --job-name=drought_dl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:TERM@300
#

set -euo pipefail

mkdir -p logs

echo "Host: $(hostname)"
echo "Start: $(date)"

uv run --frozen python pipeline_download.py

echo "End: $(date)"
