"""Generate every drought map figure for a zoomed geographic subset."""

import argparse
import subprocess
import sys
from pathlib import Path

from region_subset import REGIONS

DATA_VIZ_DIR = Path(__file__).resolve().parent

PLOT_SCRIPTS = (
    "plot_tp.py",
    "plot_pntp.py",
    "plot_swe.py",
    "plot_pnswe.py",
    "plot_spi.py",
    "plot_spei.py",
    "plot_smd.py",
    "plot_by_interval.py",
    "plot_by_interval_no_tp_swe.py",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all data_viz plotting scripts for a zoomed region."
    )
    parser.add_argument(
        "--region",
        choices=sorted(REGIONS),
        default="interior_alaska",
        help="Predefined subset (default: interior_alaska, 64×64 cells)",
    )
    args = parser.parse_args()

    for script in PLOT_SCRIPTS:
        cmd = [sys.executable, str(DATA_VIZ_DIR / script), "--region", args.region]
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=DATA_VIZ_DIR.parent)


if __name__ == "__main__":
    main()
