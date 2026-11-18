"""Check that the monthly recurring download holds the same values as the old one.

Run the old chunked download (current_month / previous_year / current_year files)
and the new monthly download on the same day into two separate recent-data
directories, then point this script at both:

    python -m qc.compare_download_values OLD_RECENT_DATA_DIR NEW_RECENT_DATA_DIR

For each variable it opens both copies, keeps the dates they share, and
compares every value exactly (missing values must sit in the same places).
It exits non-zero if any variable differs or shares no dates.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from era5_land_variable_registry import VARIABLE_REGISTRY
from file_helpers import ds_combination

OLD_CHUNK_TAGS = ("previous_year", "current_year", "current_month")


def old_chunk_files(root: Path, variable_key: str) -> list[Path]:
    meta = VARIABLE_REGISTRY[variable_key]
    folder = root / meta["recent_dir"]
    files = [
        folder / f"{meta['prefix']}{tag}{meta['suffix']}" for tag in OLD_CHUNK_TAGS
    ]
    return [f for f in files if f.exists()]


def new_monthly_files(root: Path, variable_key: str) -> list[Path]:
    meta = VARIABLE_REGISTRY[variable_key]
    folder = root / meta["recent_dir"]
    pattern = f"{meta['prefix']}[0-9][0-9][0-9][0-9]-[0-9][0-9]{meta['suffix']}"
    return sorted(folder.glob(pattern))


def compare_arrays(old: xr.DataArray, new: xr.DataArray) -> dict:
    """Compare two arrays over the dates they share."""
    shared = np.intersect1d(old["valid_time"].values, new["valid_time"].values)
    old_s = old.sel(valid_time=shared)
    new_s = new.sel(valid_time=shared)
    old_s, new_s = xr.align(old_s, new_s, join="exact")
    a = old_s.values
    b = new_s.values
    nan_mismatch = int(np.count_nonzero(np.isnan(a) != np.isnan(b)))
    both = ~np.isnan(a) & ~np.isnan(b)
    differing = int(np.count_nonzero(a[both] != b[both]))
    max_abs = float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0
    return {
        "shared_dates": len(shared),
        "differing_values": differing,
        "missing_value_mismatches": nan_mismatch,
        "max_abs_difference": max_abs,
    }


def compare_variable(old_root: Path, new_root: Path, variable_key: str) -> dict:
    meta = VARIABLE_REGISTRY[variable_key]
    old_files = old_chunk_files(old_root, variable_key)
    new_files = new_monthly_files(new_root, variable_key)
    if not old_files or not new_files:
        return {"error": f"old files: {len(old_files)}, new files: {len(new_files)}"}
    with (
        ds_combination(old_files, meta["suffix"]) as old_ds,
        ds_combination(new_files, meta["suffix"]) as new_ds,
    ):
        name = meta["short_name"]
        return compare_arrays(old_ds[name].load(), new_ds[name].load())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("old_root", type=Path, help="Recent data from the old download")
    parser.add_argument("new_root", type=Path, help="Recent data from the new download")
    args = parser.parse_args()

    all_equal = True
    for variable_key in VARIABLE_REGISTRY:
        result = compare_variable(args.old_root, args.new_root, variable_key)
        print(f"{variable_key}: {result}")
        if (
            "error" in result
            or result["shared_dates"] == 0
            or result["differing_values"]
            or result["missing_value_mismatches"]
        ):
            all_equal = False

    print("All values identical." if all_equal else "Differences found.")
    return 0 if all_equal else 1


if __name__ == "__main__":
    sys.exit(main())
