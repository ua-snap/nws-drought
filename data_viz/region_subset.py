"""Spatial subsets for zoomed drought map plots.

ERA5-Land drought outputs use ~0.1° grid spacing (~9 km). A 64×64 cell window
covers roughly 576 km on each axis in index space.
"""

from dataclasses import dataclass

import numpy as np
import xarray as xr

# Native ERA5-Land spacing; domain NetCDFs use 0.1° lat/lon steps.
GRID_CELL_KM = 9.0


@dataclass(frozen=True)
class PlotRegion:
    """Square grid-cell window centered on a lat/lon point."""

    name: str
    label: str
    center_lat: float
    center_lon: float
    n_cells: int = 64

    @property
    def slug(self) -> str:
        return self.name


# Fairbanks / central Interior Alaska (~64.5°N, 147°W).
INTERIOR_ALASKA = PlotRegion(
    name="interior_alaska",
    label="Interior Alaska",
    center_lat=64.5,
    center_lon=-147.0,
    n_cells=64,
)

# Alaska Panhandle, centered on Juneau (~58.3°N, 134.4°W).
SOUTHEAST_ALASKA = PlotRegion(
    name="southeast_alaska",
    label="Southeast Alaska",
    center_lat=58.30,
    center_lon=-134.42,
    n_cells=64,
)

# Yukon–Kuskokwim delta, centered on Bethel (~60.8°N, 161.8°W).
SOUTHWEST_ALASKA = PlotRegion(
    name="southwest_alaska",
    label="Southwest Alaska",
    center_lat=60.79,
    center_lon=-161.76,
    n_cells=64,
)

REGIONS: dict[str, PlotRegion] = {
    INTERIOR_ALASKA.name: INTERIOR_ALASKA,
    SOUTHEAST_ALASKA.name: SOUTHEAST_ALASKA,
    SOUTHWEST_ALASKA.name: SOUTHWEST_ALASKA,
}


def slice_indices(
    lat: np.ndarray,
    lon: np.ndarray,
    region: PlotRegion,
) -> tuple[slice, slice]:
    """Return lat/lon index slices for a square ``region.n_cells`` window."""

    i_center = int(np.argmin(np.abs(lat - region.center_lat)))
    j_center = int(np.argmin(np.abs(lon - region.center_lon)))
    half = region.n_cells // 2
    i0 = i_center - half
    i1 = i_center + half
    j0 = j_center - half
    j1 = j_center + half

    if i0 < 0 or i1 > len(lat) or j0 < 0 or j1 > len(lon):
        raise ValueError(
            f"Region {region.name!r} ({region.n_cells}×{region.n_cells} cells "
            f"centered on {region.center_lat}°N, {region.center_lon}°E) extends "
            f"outside the grid (lat n={len(lat)}, lon n={len(lon)})."
        )

    return slice(i0, i1), slice(j0, j1)


def subset_for_pcolormesh(
    ds: xr.Dataset,
    da: xr.DataArray,
    region: PlotRegion | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return lon, lat, and values arrays for ``pcolormesh``."""

    lat = ds["latitude"].values
    lon = ds["longitude"].values
    values = da.values

    if region is None:
        return lon, lat, values

    lat_sl, lon_sl = slice_indices(lat, lon, region)
    return (
        lon[lon_sl],
        lat[lat_sl],
        values[lat_sl, lon_sl],
    )


def region_title_suffix(region: PlotRegion | None) -> str:
    if region is None:
        return ""
    return f" — {region.label}"


def region_output_dir(base_dir, region: PlotRegion | None):
    from pathlib import Path

    base = Path(base_dir)
    if region is None:
        return base
    return base / region.slug
