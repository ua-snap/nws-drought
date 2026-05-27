"""Map projections for drought plots."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from matplotlib.axes import Axes
import cartopy.crs as ccrs

from plot_scales import NO_DATA_FILL

# Gridded fields are on geographic lon/lat (ERA5 convention).
DATA_CRS = ccrs.PlateCarree()

MAP_CRS = ccrs.epsg(3338)

# Areas outside the gridded data (viewport margins, projection corners).
PLOT_BACKGROUND = NO_DATA_FILL


def projected_bounds_from_lonlat(
    lon: np.ndarray,
    lat: np.ndarray,
    *,
    pad_fraction: float = 0.02,
) -> tuple[float, float, float, float]:
    """Axis-aligned EPSG:3338 bounds covering all lon/lat grid nodes."""

    lon2d, lat2d = np.meshgrid(lon, lat)
    pts = MAP_CRS.transform_points(DATA_CRS, lon2d.ravel(), lat2d.ravel())
    x = pts[:, 0]
    y = pts[:, 1]
    x0, x1 = float(x.min()), float(x.max())
    y0, y1 = float(y.min()), float(y.max())
    pad_x = (x1 - x0) * pad_fraction
    pad_y = (y1 - y0) * pad_fraction
    return x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y


def projected_bounds_from_corners(
    corners_latlon: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Axis-aligned EPSG:3338 bounds covering region corners."""

    lat = np.array([corner[0] for corner in corners_latlon])
    lon = np.array([corner[1] for corner in corners_latlon])
    pts = MAP_CRS.transform_points(DATA_CRS, lon, lat)
    x = pts[:, 0]
    y = pts[:, 1]
    return float(x.min()), float(x.max()), float(y.min()), float(y.max())


def projected_aspect_ratio_from_corners(
    corners_latlon: Sequence[tuple[float, float]],
) -> float:
    """Width / height of a region display box in EPSG:3338."""

    x0, x1, y0, y1 = projected_bounds_from_corners(corners_latlon)
    return (x1 - x0) / (y1 - y0)


def projected_aspect_ratio_from_grid(lon: np.ndarray, lat: np.ndarray) -> float:
    """Width / height of a lon/lat grid footprint in EPSG:3338."""

    x0, x1, y0, y1 = projected_bounds_from_lonlat(lon, lat)
    return (x1 - x0) / (y1 - y0)


def set_extent_from_grid(ax: Axes, lon: np.ndarray, lat: np.ndarray) -> None:
    """Frame the map to the projected footprint of the plotted grid."""

    x0, x1, y0, y1 = projected_bounds_from_lonlat(lon, lat)
    ax.set_extent([x0, x1, y0, y1], crs=MAP_CRS)


def set_extent_from_corners(
    ax: Axes,
    corners_latlon: Sequence[tuple[float, float]],
) -> None:
    """Frame the map to an explicit EPSG:3338 region display box."""

    x0, x1, y0, y1 = projected_bounds_from_corners(corners_latlon)
    ax.set_extent([x0, x1, y0, y1], crs=MAP_CRS)
