#!/bin/bash
#SBATCH --job-name=drought_run
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=t2small
#SBATCH --time=01:00:00
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
echo "Running drought indicators pipeline..."

uv run --frozen python pipeline_run.py

echo "End: $(date)"
