"""General set of helper functions for file navigation."""

import logging
from pathlib import Path

import xarray as xr

from era5_land_variable_registry import VARIABLE_REGISTRY

NETCDF_ENGINE = "h5netcdf"


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def year_from_input_filename(name: str, *, prefix: str, suffix: str) -> int:
    if not (name.startswith(prefix) and name.endswith(suffix)):
        raise ValueError(f"Expected filename like {prefix}1993{suffix}, got {name!r}")
    year = name[len(prefix) : -len(suffix)]
    if len(year) != 4 or not year.isdecimal():
        raise ValueError(f"Expected filename like {prefix}1993{suffix}, got {name!r}")
    return int(year)


def discover_year_files(
    input_dir: Path, variable_key: str, suffix: str
) -> dict[int, Path]:
    """Discover yearly files for the selected registry variable."""
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    prefix = VARIABLE_REGISTRY[variable_key]["prefix"]
    paths = sorted(p for p in input_dir.glob(f"{prefix}*{suffix}") if p.is_file())
    if not paths:
        raise FileNotFoundError(
            f"No files matching {prefix}*{suffix} found in {input_dir}"
        )

    year_to_path: dict[int, Path] = {}
    for path in paths:
        year = year_from_input_filename(path.name, prefix=prefix, suffix=suffix)
        if year in year_to_path:
            raise ValueError(
                f"Multiple files appear to map to year {year}: "
                f"{year_to_path[year].name}, {path.name}"
            )
        year_to_path[year] = path

    return dict(sorted(year_to_path.items()))


def ds_combination(fps_to_open: list, suffix: str) -> xr.Dataset:
    if suffix == ".grib":
        ds = xr.open_mfdataset(
            fps_to_open,
            engine="cfgrib",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            backend_kwargs={
                "time_dims": ["valid_time"],
                "coords_as_attributes": ["surface", "number"],
                "indexpath": "",  # grib can spew auxillary .idx files, this halts that behavior
            },
        )
    else:
        ds = xr.open_mfdataset(
            fps_to_open,
            combine="by_coords",
            engine=NETCDF_ENGINE,
            data_vars="minimal",
            coords="minimal",
            compat="override",
        ).sortby("valid_time")
    return ds


# helper function
# for the year 1981, we should drop the first time slice because that value will actually be for the last day of the prior-year
