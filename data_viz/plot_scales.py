"""Shared scales, categorical colorbar ticks, and display titles for drought map plots."""

from dataclasses import dataclass

from matplotlib.colors import BoundaryNorm, ListedColormap

# SPI / SPEI (USDM): 11 categories from D4 through Excp Moist.
# Thresholds match the U.S. Drought Monitor SPI legend.
SPI_SPEI_USDM_BOUNDS = (
    -4.0,
    -2.0,
    -1.6,
    -1.3,
    -0.8,
    -0.5,
    0.5,
    0.8,
    1.3,
    1.6,
    2.0,
    4.0,
)

SPI_SPEI_USDM_COLORS = (
    "#730000",  # D4 (≤ -2.00)
    "#e60000",  # D3
    "#ffaa00",  # D2
    "#fcd37f",  # D1
    "#ffff00",  # D0
    "#ffffff",  # Normal (±0.5)
    "#c2e699",  # Abn Moist (+0.51)
    "#1b7837",  # Mod Moist
    "#4575b4",  # Very Moist
    "#253494",  # Extr Moist
    "#762a83",  # Excp Moist (≥ +2.00)
)

SPI_SPEI_USDM_CBAR_LABELS = (
    "≤ -2.00\n(D4)",
    "-2.00 to -1.60\n(D3)",
    "-1.60 to -1.30\n(D2)",
    "-1.30 to -0.80\n(D1)",
    "-0.80 to -0.50\n(D0)",
    "-0.50 to 0.50\n(Normal)",
    "0.50 to 0.80\n(Abn Moist)",
    "0.80 to 1.30\n(Mod Moist)",
    "1.30 to 1.60\n(Very Moist)",
    "1.60 to 2.00\n(Extr Moist)",
    "≥ 2.00\n(Excp Moist)",
)

SPI_SPEI_USDM_CBAR_TICKS = (
    -3.0,
    -1.8,
    -1.45,
    -1.05,
    -0.65,
    0.0,
    0.65,
    1.05,
    1.45,
    1.8,
    3.0,
)

# Single fill for oceans, invalid/masked cells, and subplot margins on all drought maps.
# Cool blue-gray slate: avoids confusion with ramps (snow blues, normals white, glaciers #bdbdbd).
NO_DATA_FILL = "#8f96a8"


@dataclass(frozen=True)
class PlotScale:
    """Discrete scale for map grids.

    Names:
        indicator_title: figure suptitle / exports ("full" name).
        panel_title: short subplot title when many maps share a figure.
        colorbar_axis_label: matplotlib colorbar label (often with units).

    categorical tick text for the color ramp lives in ``cbar_labels``.
    Invalid / masked raster cells use ``NO_DATA_FILL`` (see ``mask_color``).
    """

    bounds: tuple[float, ...]
    colors: tuple[str, ...]
    cbar_labels: tuple[str, ...]
    cbar_ticks: tuple[float, ...]
    indicator_title: str
    panel_title: str
    colorbar_axis_label: str
    mask_color: str = NO_DATA_FILL
    clip: bool = True


SPI_USDM_SCALE = PlotScale(
    bounds=SPI_SPEI_USDM_BOUNDS,
    colors=SPI_SPEI_USDM_COLORS,
    cbar_labels=SPI_SPEI_USDM_CBAR_LABELS,
    cbar_ticks=SPI_SPEI_USDM_CBAR_TICKS,
    indicator_title="Standardized Precipitation Index",
    panel_title="SPI",
    colorbar_axis_label="SPI",
)

SPEI_USDM_SCALE = PlotScale(
    bounds=SPI_SPEI_USDM_BOUNDS,
    colors=SPI_SPEI_USDM_COLORS,
    cbar_labels=SPI_SPEI_USDM_CBAR_LABELS,
    cbar_ticks=SPI_SPEI_USDM_CBAR_TICKS,
    indicator_title="Standardized Precipitation Evapotranspiration Index",
    panel_title="SPEI",
    colorbar_axis_label="SPEI",
)

TP_SCALE = PlotScale(
    bounds=(0, 1, 2.5, 5, 10, 20, 50, 100, 200, 400, 600),
    colors=(
        "#f7fbff",
        "#deebf7",
        "#c6dbef",
        "#9ecae1",
        "#6baed6",
        "#4292c6",
        "#2171b5",
        "#08519c",
        "#08306b",
        "#3f007d",
    ),
    cbar_labels=(
        "0 to 1",
        "1 to 2.5",
        "2.5 to 5",
        "5 to 10",
        "10 to 20",
        "20 to 50",
        "50 to 100",
        "100 to 200",
        "200 to 400",
        "400 to 600",
    ),
    cbar_ticks=(0.5, 1.75, 3.75, 7.5, 15, 35, 75, 150, 300, 500),
    indicator_title="Total Precipitation",
    panel_title="Total Precipitation",
    colorbar_axis_label="Total precipitation (cm)",
)

SMD_SCALE = PlotScale(
    bounds=(-100, -40, -30, -20, -10, 0, 100),
    colors=(
        "#7f0000",
        "#d73027",
        "#fc8d59",
        "#fee08b",
        "#ffffbf",
        "#1a9850",
    ),
    cbar_labels=(
        "< -40",
        "-40 to -30",
        "-30 to -20",
        "-20 to -10",
        "-10 to 0",
        "> 0",
    ),
    cbar_ticks=(-70, -35, -25, -15, -5, 50),
    indicator_title="Soil Moisture Percent of Normal",
    panel_title="Soil Moisture Percent of Normal",
    colorbar_axis_label="Soil moisture percent of normal (%)",
)

SWE_SCALE = PlotScale(
    bounds=(0, 1, 5, 10, 20, 40, 75, 125, 200, 350, 999.5, 1000.5),
    colors=(
        "#f3fbff",
        "#eef8ff",
        "#d6efff",
        "#b9e3ff",
        "#8fceef",
        "#63b3df",
        "#3c93c8",
        "#2070aa",
        "#084a8d",
        "#54278f",
        "#bdbdbd",
    ),
    cbar_labels=(
        "0–1",
        "1–5",
        "5–10",
        "10–20",
        "20–40",
        "40–75",
        "75–125",
        "125–200",
        "200–350",
        "350–<1000",
        "Glacier",
    ),
    cbar_ticks=(0.5, 3, 7.5, 15, 30, 57.5, 100, 162.5, 275, 675, 1000),
    indicator_title="Snow Water Equivalent",
    panel_title="Snow Water Equivalent",
    colorbar_axis_label="SWE (cm)",
)

PNTP_SCALE = PlotScale(
    bounds=(0, 25, 50, 70, 90, 110, 130, 150, 200, 300, 500, 700),
    colors=(
        "#7f0000",
        "#d7301f",
        "#fc8d59",
        "#fdcc8a",
        "#f7f7f7",
        "#d9f0d3",
        "#a6d96a",
        "#66bd63",
        "#1a9850",
        "#2b8cbe",
        "#084081",
    ),
    cbar_labels=(
        "0–25",
        "25–50",
        "50–70",
        "70–90",
        "90–110",
        "110–130",
        "130–150",
        "150–200",
        "200–300",
        "300–500",
        "500–700",
    ),
    cbar_ticks=(12.5, 37.5, 60, 80, 100, 120, 140, 175, 250, 400, 600),
    indicator_title="Precipitation Percent of Normal",
    panel_title="Precipitation Percent of Normal",
    colorbar_axis_label="Precipitation percent of normal (%)",
)

PNSWE_SCALE = PlotScale(
    bounds=(-0.5, 0.5, 25, 50, 75, 90, 110, 125, 150, 200, 300, 500, 2500),
    colors=(
        "#5a0000",
        "#b30000",
        "#e34a33",
        "#fc8d59",
        "#fdcc8a",
        "#f7f7f7",
        "#d9f0ff",
        "#b9e3ff",
        "#8fceef",
        "#4eb3d3",
        "#2b8cbe",
        "#54278f",
    ),
    cbar_labels=(
        "0",
        "0–25",
        "25–50",
        "50–75",
        "75–90",
        "90–110",
        "110–125",
        "125–150",
        "150–200",
        "200–300",
        "300–500",
        ">500",
    ),
    cbar_ticks=(0, 12.5, 37.5, 62.5, 82.5, 100, 117.5, 137.5, 175, 250, 400, 1500),
    indicator_title="Snow Water Equivalent Percent of Normal",
    panel_title="Snow Water Equivalent Percent of Normal",
    colorbar_axis_label="Percent of normal SWE (%)",
)


def make_colormap(scale: PlotScale) -> tuple[ListedColormap, BoundaryNorm]:
    """Build a ListedColormap and BoundaryNorm from a PlotScale."""
    cmap = ListedColormap(scale.colors)
    cmap.set_bad(scale.mask_color)
    norm = BoundaryNorm(scale.bounds, cmap.N, clip=scale.clip)
    return cmap, norm


# Convenience map from NetCDF-style variable keys to PlotScale (titles live on each scale).
SCALES_BY_VARIABLE_KEY: dict[str, PlotScale] = {
    "tp": TP_SCALE,
    "pntp": PNTP_SCALE,
    "swe": SWE_SCALE,
    "pnswe": PNSWE_SCALE,
    "spi": SPI_USDM_SCALE,
    "spei": SPEI_USDM_SCALE,
    "smd": SMD_SCALE,
}
