"""Major-river overlays for regional drought map figures.

The canonical Alaska five (Yukon, Kuskokwim, Tanana, Copper, Susitna) are
drawn only on interior and southwest regional subsets. Full-domain and
southeast Alaska figures omit river lines.

River geometries come from Natural Earth at 10 m resolution. Most rivers live
in ``ne_10m_rivers_lake_centerlines``; the Taku and several Kuskokwim
tributaries are only present in the supplemental ``ne_10m_rivers_north_america``
dataset, so both are loaded and merged. Cartopy downloads and caches each
shapefile on first use.
"""

from functools import lru_cache

import matplotlib.patheffects as pe
from cartopy.feature import ShapelyFeature
from cartopy.io import shapereader
from matplotlib.axes import Axes
from shapely.geometry.base import BaseGeometry

from plot_crs import DATA_CRS
from region_subset import PlotRegion

# Canonical river -> Natural Earth ``name`` attributes that represent it.
# Includes named tributaries / forks so each watershed renders as a connected
# system rather than just its trunk. Matching is case-sensitive and exact,
# which keeps ``"Copper"`` from also pulling in Canada's ``"Coppermine"`` river.
NAMES_BY_RIVER: dict[str, frozenset[str]] = {
    "Yukon": frozenset({"Yukon"}),
    "Kuskokwim": frozenset(
        {
            "Kuskokwim",
            "North Fork Kuskokwim",
            "S. Fork Kuskokwim",
            "East Fork Kuskokwim",
            "E.  Fk.  Kuskokwim",
        }
    ),
    "Tanana": frozenset({"Tanana"}),
    "Copper": frozenset({"Copper"}),
    "Susitna": frozenset({"Susitna"}),
}

# Order matters only for predictable z-stacking when rivers overlap.
NE_RIVER_SOURCES: tuple[tuple[str, str], ...] = (
    ("physical", "rivers_lake_centerlines"),
    ("physical", "rivers_north_america"),
)

DEFAULT_RIVERS: tuple[str, ...] = (
    "Yukon",
    "Kuskokwim",
    "Tanana",
    "Copper",
    "Susitna",
)

REGION_RIVER_NAMES: dict[str, tuple[str, ...]] = {
    "interior_alaska": DEFAULT_RIVERS,
    "southwest_alaska": DEFAULT_RIVERS,
}

RIVER_COLOR = "#1f4e8c"
RIVER_LINEWIDTH = 1.2
RIVER_HALO_COLOR = "white"
RIVER_HALO_WIDTH = 2.4
# Above the pcolormesh raster, below community markers (zorder 10/11).
RIVER_ZORDER = 8


@lru_cache(maxsize=None)
def _river_geometries(river: str) -> tuple[BaseGeometry, ...]:
    """Return Natural Earth geometries for one canonical river name."""

    wanted = NAMES_BY_RIVER[river]
    geoms: list[BaseGeometry] = []
    for category, source_name in NE_RIVER_SOURCES:
        shp_path = shapereader.natural_earth(
            resolution="10m", category=category, name=source_name
        )
        for record in shapereader.Reader(shp_path).records():
            ne_name = record.attributes.get("name")
            if ne_name in wanted:
                geoms.append(record.geometry)
    return tuple(geoms)


def rivers_for_region(region: PlotRegion | None) -> tuple[str, ...]:
    """Return river names to overlay for a plot scope, or ``()`` if none."""

    if region is None:
        return ()
    return REGION_RIVER_NAMES.get(region.name, ())


def add_rivers_to_axes(ax: Axes, region: PlotRegion | None) -> None:
    """Draw Alaska river centerlines for the configured scope onto ``ax``.

    Geometries are added as a single :class:`cartopy.feature.ShapelyFeature`,
    so cartopy handles clipping to the axes extent. Rivers outside a regional
    window therefore disappear without any manual filtering.
    """

    river_names = rivers_for_region(region)
    geometries: list[BaseGeometry] = []
    for river in river_names:
        geometries.extend(_river_geometries(river))
    if not geometries:
        return

    feature = ShapelyFeature(
        geometries,
        DATA_CRS,
        edgecolor=RIVER_COLOR,
        facecolor="none",
        linewidth=RIVER_LINEWIDTH,
        zorder=RIVER_ZORDER,
    )
    artist = ax.add_feature(feature)
    artist.set_path_effects(
        [
            pe.withStroke(linewidth=RIVER_HALO_WIDTH, foreground=RIVER_HALO_COLOR),
            pe.Normal(),
        ]
    )
