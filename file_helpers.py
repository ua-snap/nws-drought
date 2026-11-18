"""General set of helper functions for file navigation."""

import logging
from pathlib import Path

import numpy as np
import xarray as xr

from era5_land_variable_registry import VARIABLE_REGISTRY

NETCDF_ENGINE = "h5netcdf"
GRIB_BACKEND_KWARGS = {
    "time_dims": ["valid_time"],
    "coords_as_attributes": ["surface", "number"],
    "indexpath": "",  # grib can spew auxillary .idx files, this halts that behavior
}


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
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


def _valid_time_as_dimension(ds: xr.Dataset) -> xr.Dataset:
    return ds if "valid_time" in ds.dims else ds.expand_dims("valid_time")


def ds_combination(fps_to_open: list, suffix: str) -> xr.Dataset:
    if suffix == ".grib":
        ds = xr.open_mfdataset(
            fps_to_open,
            engine="cfgrib",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            backend_kwargs=GRIB_BACKEND_KWARGS,
            # a file holding one date decodes to a scalar valid_time, which
            # cannot be concatenated until it is a dimension again
            preprocess=_valid_time_as_dimension,
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


def check_output_file(
    path: Path, short_name: str, expected_dates: list
) -> tuple[bool, str]:
    """Check that a downloaded file holds the variable and exactly the dates expected.

    ``expected_dates`` are the valid dates (for 00:00 accumulations, the valid_time
    label, per the download convention). Dates compare at day resolution.
    Returns (passed, reason); never raises for an unreadable file.
    """
    path = Path(path)
    try:
        if path.suffix == ".grib":
            ds = xr.open_dataset(
                path, engine="cfgrib", backend_kwargs=GRIB_BACKEND_KWARGS
            )
        else:
            ds = xr.open_dataset(path, engine=NETCDF_ENGINE)
        with ds:
            has_variable = short_name in ds.data_vars
            # a file holding one date (e.g. a single 00 UTC accumulation)
            # decodes to a scalar valid_time
            found = set(np.atleast_1d(ds["valid_time"].values).astype("datetime64[D]"))
    except Exception as exc:
        return False, f"{path.name} could not be opened or read: {exc}"

    if not has_variable:
        return False, f"{path.name} does not contain variable {short_name!r}"
    expected = set(np.array(expected_dates, dtype="datetime64[D]"))
    if found != expected:
        missing = sorted(str(d) for d in expected - found)
        extra = sorted(str(d) for d in found - expected)
        return False, (
            f"{path.name} dates differ from expected: "
            f"missing {missing[:3]}{'...' if len(missing) > 3 else ''}, "
            f"unexpected {extra[:3]}{'...' if len(extra) > 3 else ''}"
        )
    return (
        True,
        f"{path.name} holds {short_name} for all {len(expected)} expected dates",
    )
