"""Spatial subsets for zoomed drought map plots.

ERA5-Land drought outputs use ~0.1° grid spacing (~9 km). Regional windows are
defined by their display bounds in lat/lon, plus a small source-data buffer so
projected plots are filled to the EPSG:3338 axes extent.
"""

from dataclasses import dataclass

import numpy as np
import xarray as xr

# Native ERA5-Land spacing; domain NetCDFs use 0.1° lat/lon steps.
GRID_CELL_KM = 9.0


@dataclass(frozen=True)
class PlotRegion:
    """Lat/lon display bounds for a regional projected map."""

    name: str
    label: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    source_padding_cells: int = 14

    @property
    def slug(self) -> str:
        return self.name

    @property
    def corners_latlon(self) -> tuple[tuple[float, float], ...]:
        """Display-box corners as ``(lat, lon)`` pairs."""

        return (
            (self.lat_max, self.lon_min),
            (self.lat_max, self.lon_max),
            (self.lat_min, self.lon_max),
            (self.lat_min, self.lon_min),
        )


# Fairbanks / central Interior Alaska (~64.5°N, 147°W).
INTERIOR_ALASKA = PlotRegion(
    name="interior_alaska",
    label="Interior Alaska",
    lat_min=62.5,
    lat_max=66.5,
    lon_min=-151.6,
    lon_max=-142.4,
)


SOUTHEAST_ALASKA = PlotRegion(
    name="southeast_alaska",
    label="Southeast Alaska",
    lat_min=56.3,
    lat_max=60.3,
    lon_min=-138.2,
    lon_max=-130.6,
)


SOUTHWEST_ALASKA = PlotRegion(
    name="southwest_alaska",
    label="Southwest Alaska",
    lat_min=58.8,
    lat_max=62.8,
    lon_min=-163.8,
    lon_max=-155.8,
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
    """Return buffered lat/lon index slices that cover a ``region`` window."""

    lat_matches = np.flatnonzero((lat >= region.lat_min) & (lat <= region.lat_max))
    lon_matches = np.flatnonzero((lon >= region.lon_min) & (lon <= region.lon_max))
    if len(lat_matches) == 0 or len(lon_matches) == 0:
        raise ValueError(
            f"Region {region.name!r} does not overlap the grid "
            f"(lat n={len(lat)}, lon n={len(lon)})."
        )

    pad = region.source_padding_cells
    i0 = int(lat_matches.min()) - pad
    i1 = int(lat_matches.max()) + pad + 1
    j0 = int(lon_matches.min()) - pad
    j1 = int(lon_matches.max()) + pad + 1

    if i0 < 0 or i1 > len(lat) or j0 < 0 or j1 > len(lon):
        raise ValueError(
            f"Region {region.name!r} plus {pad} padding cells extends outside "
            f"the grid (lat n={len(lat)}, lon n={len(lon)})."
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
