"""Shared paths, NetCDF helpers, and cross-interval plotting for drought maps."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_communities import add_communities_to_axes
from plot_rivers import add_rivers_to_axes
from plot_crs import (
    DATA_CRS,
    MAP_CRS,
    PLOT_BACKGROUND,
    projected_aspect_ratio_from_corners,
    projected_aspect_ratio_from_grid,
    set_extent_from_corners,
    set_extent_from_grid,
)
from plot_scales import PlotScale, make_colormap
from region_subset import (
    PlotRegion,
    region_title_suffix,
    subset_for_pcolormesh,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import INDICES_DIR, INTERVALS  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent
FIGURES_ROOT = OUTPUT_DIR / "figures"

# Descriptive subdirectories under ``figures/`` for collaborator-friendly browsing.
BY_INDICATOR_DIR = "by_indicator"
BY_INDICATOR_INTERVAL_DIR = "by_indicator_interval"
BY_SUMMARY_INTERVAL_DIR = "by_summary_interval"
BY_SUMMARY_INTERVAL_FIVE_PANEL_DIR = "by_summary_interval_five_panel"
FULL_DOMAIN_SLUG = "full_domain"

VARIABLE_OUTPUT_FILENAMES: dict[str, str] = {
    "tp": "total_precipitation.png",
    "pntp": "precip_percent_of_normal.png",
    "swe": "snow_water_equivalent.png",
    "pnswe": "swe_percent_of_normal.png",
    "spi": "spi.png",
    "spei": "spei.png",
    "smd": "soil_moisture_deficit.png",
}

DATED_INDICES_GLOB = "drought_indices_{days}day_*.nc"


def parse_drought_indices_path(path: Path) -> tuple[int, str, str]:
    """Parse ``drought_indices_<n>day_<YYYY>_<MM>_<DD>.nc``."""

    parts = Path(path).stem.split("_")
    if len(parts) != 6 or parts[0] != "drought" or parts[1] != "indices":
        raise ValueError(
            f"Expected drought_indices_<n>day_<YYYY>_<MM>_<DD>.nc, got {path.name!r}"
        )

    interval_token = parts[2]
    if not interval_token.endswith("day"):
        raise ValueError(f"Invalid interval token in {path.name!r}: {interval_token!r}")

    days = int(interval_token.removesuffix("day"))
    reference_date = "-".join(parts[3:6])
    interval_label = interval_token
    return days, reference_date, interval_label


def interval_netcdf_path(data_dir: Path, days: int) -> Path:
    """Return the single dated NetCDF for one summary interval."""

    matches = sorted(data_dir.glob(DATED_INDICES_GLOB.format(days=days)))
    expected = f"drought_indices_{days}day_<YYYY>_<MM>_<DD>.nc"
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one {expected} under {data_dir}, found {len(matches)}"
        )
    return matches[0]


def all_interval_netcdf_paths(data_dir: Path = INDICES_DIR) -> list[Path]:
    """Return one dated NetCDF per configured summary interval, in ``INTERVALS`` order."""

    return [interval_netcdf_path(data_dir, days) for days in INTERVALS]


def masked_for_land(ds: xr.Dataset, da: xr.DataArray) -> xr.DataArray:
    """Mask ocean/non-land consistently with existing variable plots."""

    return da.where(ds["smd"].notnull())


def plot_variable_across_files(
    paths: list[str | Path],
    *,
    variable_key: str,
    scale: PlotScale,
    region: PlotRegion | None = None,
    figsize_per_panel: tuple[float, float] = (5.5, 4.0),
    save_path: str | Path | None = None,
    mask_land: bool = True,
) -> plt.Figure:
    """Compare one indicator across multiple summary-interval NetCDF files."""

    path_objs = [Path(path) for path in paths]
    n_intervals = len(path_objs)
    ncols = 3
    nrows = math.ceil(n_intervals / ncols)
    cmap, norm = make_colormap(scale)

    opened: list[tuple[Path, xr.Dataset]] = []
    for path in path_objs:
        opened.append((path, xr.open_dataset(path)))

    if region is None:
        reference_ds = opened[0][1]
        proj_aspect = projected_aspect_ratio_from_grid(
            reference_ds["longitude"].values,
            reference_ds["latitude"].values,
        )
    else:
        proj_aspect = projected_aspect_ratio_from_corners(region.corners_latlon)

    panel_size = (figsize_per_panel[1] * proj_aspect, figsize_per_panel[1])

    _, reference_date, _ = parse_drought_indices_path(path_objs[0])
    mesh = None

    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(panel_size[0] * ncols, panel_size[1] * nrows),
        constrained_layout=True,
        squeeze=False,
        subplot_kw={"projection": MAP_CRS},
    )
    fig.patch.set_facecolor("white")

    for ax, (path, ds) in zip(axes.flat, opened, strict=False):
        _, _, interval_label = parse_drought_indices_path(path)

        da = ds[variable_key]
        if mask_land:
            da = masked_for_land(ds, da)

        lon, lat, values = subset_for_pcolormesh(ds, da, region)
        mesh = ax.pcolormesh(
            lon,
            lat,
            values,
            shading="auto",
            cmap=cmap,
            norm=norm,
            transform=DATA_CRS,
        )
        add_rivers_to_axes(ax, region)
        add_communities_to_axes(ax, region, lon, lat)

        ax.set_title(interval_label)
        ax.label_outer()
        ax.set_facecolor(PLOT_BACKGROUND)

    for ax in axes.flat[:n_intervals]:
        if region is None:
            set_extent_from_grid(ax, lon, lat)
        else:
            set_extent_from_corners(ax, region.corners_latlon)

    for ax_unused in axes.flat[n_intervals:]:
        ax_unused.axis("off")

    for _, ds in opened:
        ds.close()

    if mesh is None:
        raise ValueError("No input files were provided.")

    cbar = fig.colorbar(
        mesh,
        ax=axes.ravel().tolist(),
        boundaries=scale.bounds,
        ticks=scale.cbar_ticks,
        spacing="uniform",
    )
    cbar.set_ticklabels(scale.cbar_labels)
    cbar.set_label(scale.colorbar_axis_label)

    fig.suptitle(
        f"{scale.indicator_title}{region_title_suffix(region)} — "
        f"Reference Date {reference_date}",
        fontsize=12,
    )

    if save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig


def parse_region_arg(region_name: str | None) -> PlotRegion | None:
    from region_subset import REGIONS

    if region_name is None:
        return None
    key = region_name.lower()
    if key not in REGIONS:
        known = ", ".join(sorted(REGIONS))
        raise SystemExit(f"Unknown region {region_name!r}. Choose from: {known}")
    return REGIONS[key]


def add_region_arg(parser) -> None:
    parser.add_argument(
        "--region",
        choices=sorted(__import__("region_subset", fromlist=["REGIONS"]).REGIONS),
        default=None,
        help="Zoom to a predefined regional subset (e.g. interior_alaska)",
    )


def scope_slug(region: PlotRegion | None) -> str:
    """Geographic scope directory name under each figure category."""

    return FULL_DOMAIN_SLUG if region is None else region.slug


def figures_dir(category: str, region: PlotRegion | None = None) -> Path:
    """Return (and create) ``figures/<category>/<scope>/`` for saved PNGs."""

    out_dir = FIGURES_ROOT / category / scope_slug(region)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def output_path_for_variable(
    variable_key: str,
    region: PlotRegion | None,
) -> Path:
    filename = VARIABLE_OUTPUT_FILENAMES.get(variable_key, f"{variable_key}.png")
    return figures_dir(BY_INDICATOR_DIR, region) / filename


def output_path_for_indicator_interval(
    variable_key: str,
    days: int,
    region: PlotRegion | None,
) -> Path:
    return (
        figures_dir(BY_INDICATOR_INTERVAL_DIR, region) / f"{variable_key}_{days}day.png"
    )


def output_path_for_interval_maps(
    days: int,
    region: PlotRegion | None,
    *,
    five_panel: bool = False,
) -> Path:
    category = (
        BY_SUMMARY_INTERVAL_FIVE_PANEL_DIR if five_panel else BY_SUMMARY_INTERVAL_DIR
    )
    return figures_dir(category, region) / f"{days}day.png"
