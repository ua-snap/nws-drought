"""Community markers for regional drought map overlays."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.patheffects as pe
import numpy as np
from matplotlib.axes import Axes

from plot_crs import DATA_CRS
from region_subset import PlotRegion

COMMUNITIES_JSON = Path(__file__).resolve().parent / "communities_ak_filtered.json"

MARKER_SIZE = 7.0
MARKER_FACE = "#fff8e7"
MARKER_EDGE = "#1a1a1a"
MARKER_EDGE_WIDTH = 1.4

LABEL_FONTSIZE = 11
LABEL_FONTWEIGHT = "bold"
LABEL_COLOR = "#111111"
LABEL_OFFSET = (5, 5)
# Cream halo + thin dark ring reads on white "normal" cells and colored drought bins.
LABEL_HALO_COLOR = "#fff8e7"
LABEL_HALO_WIDTH = 4.5
LABEL_RING_COLOR = "#333333"
LABEL_RING_WIDTH = 1.2

# Four communities spread across each regional map window.
REGION_COMMUNITY_NAMES: dict[str, tuple[str, ...]] = {
    "interior_alaska": (
        "Fairbanks",
        "Delta Junction",
        "Nenana",
        "Healy",
    ),
    "southeast_alaska": (
        "Juneau",
        "Sitka",
        "Ketchikan",
        "Haines",
    ),
    "southwest_alaska": (
        "Bethel",
        "Dillingham",
        "Mountain Village",
        "Aniak",
    ),
}


def _load_communities_by_name() -> dict[str, dict]:
    with COMMUNITIES_JSON.open(encoding="utf-8") as handle:
        records = json.load(handle)
    return {record["name"]: record for record in records}


def communities_for_region(region: PlotRegion) -> list[dict]:
    """Return community records configured for a plot region."""

    names = REGION_COMMUNITY_NAMES.get(region.name)
    if not names:
        return []

    by_name = _load_communities_by_name()
    missing = [name for name in names if name not in by_name]
    if missing:
        raise KeyError(f"Communities not found in {COMMUNITIES_JSON.name}: {missing}")

    return [by_name[name] for name in names]


def _within_extent(
    lon: float,
    lat: float,
    lon_bounds: tuple[float, float],
    lat_bounds: tuple[float, float],
) -> bool:
    lon_min, lon_max = lon_bounds
    lat_min, lat_max = lat_bounds
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def add_communities_to_axes(
    ax: Axes,
    region: PlotRegion | None,
    lon: np.ndarray,
    lat: np.ndarray,
) -> None:
    """Draw community markers and labels when a regional subset is active."""

    if region is None:
        return

    communities = communities_for_region(region)
    if not communities:
        return

    lon_bounds = (float(np.min(lon)), float(np.max(lon)))
    lat_bounds = (float(np.min(lat)), float(np.max(lat)))

    for place in communities:
        place_lon = place["lon"]
        place_lat = place["lat"]
        if not _within_extent(place_lon, place_lat, lon_bounds, lat_bounds):
            continue

        ax.plot(
            place_lon,
            place_lat,
            marker="o",
            markersize=MARKER_SIZE,
            markerfacecolor=MARKER_FACE,
            markeredgecolor=MARKER_EDGE,
            markeredgewidth=MARKER_EDGE_WIDTH,
            linestyle="None",
            transform=DATA_CRS,
            zorder=10,
        )
        ax.annotate(
            place["name"],
            (place_lon, place_lat),
            xytext=LABEL_OFFSET,
            textcoords="offset points",
            fontsize=LABEL_FONTSIZE,
            fontweight=LABEL_FONTWEIGHT,
            color=LABEL_COLOR,
            transform=DATA_CRS,
            zorder=11,
            path_effects=[
                pe.withStroke(linewidth=LABEL_HALO_WIDTH, foreground=LABEL_HALO_COLOR),
                pe.withStroke(linewidth=LABEL_RING_WIDTH, foreground=LABEL_RING_COLOR),
                pe.Normal(),
            ],
        )
