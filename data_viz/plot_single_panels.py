"""Plot one drought-indicator variable for one summary interval per figure."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_common import (
    INDICES_DIR,
    INTERVALS,
    interval_netcdf_path,
    masked_for_land,
    output_path_for_indicator_interval,
    parse_drought_indices_path,
    parse_region_arg,
)
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
from plot_scales import PlotScale, SCALES_BY_VARIABLE_KEY, make_colormap
from region_subset import PlotRegion, region_title_suffix, subset_for_pcolormesh

# Order matches README indicator list and the multi-panel interval figures.
VARIABLE_PANELS: tuple[tuple[str, PlotScale], ...] = tuple(
    (variable_key, SCALES_BY_VARIABLE_KEY[variable_key])
    for variable_key in ("tp", "pntp", "swe", "pnswe", "spi", "spei", "smd")
)

FIGURE_HEIGHT = 6.0
SUPTITLE_FONTSIZE = 13
COLORBAR_TICK_FONTSIZE = 9
COLORBAR_LABEL_FONTSIZE = 10


def plot_single_variable_one_interval(
    nc_path: str | Path,
    *,
    variable_key: str,
    scale: PlotScale,
    figure_height: float = FIGURE_HEIGHT,
    save_path: str | Path | None = None,
    region: PlotRegion | None = None,
) -> plt.Figure:
    """One figure showing one indicator grid for one summary-interval file."""

    path = Path(nc_path)

    with xr.open_dataset(path) as ds:
        if region is None:
            proj_aspect = projected_aspect_ratio_from_grid(
                ds["longitude"].values,
                ds["latitude"].values,
            )
        else:
            proj_aspect = projected_aspect_ratio_from_corners(region.corners_latlon)

    fig, ax = plt.subplots(
        figsize=(figure_height * proj_aspect, figure_height),
        constrained_layout=True,
        subplot_kw={"projection": MAP_CRS},
    )
    fig.patch.set_facecolor("white")

    with xr.open_dataset(path) as ds:
        _, reference_date, interval_label = parse_drought_indices_path(path)
        da = masked_for_land(ds, ds[variable_key])
        lon, lat, values = subset_for_pcolormesh(ds, da, region)

        cmap, norm = make_colormap(scale)
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

        if region is None:
            set_extent_from_grid(ax, lon, lat)
        else:
            set_extent_from_corners(ax, region.corners_latlon)

    ax.set_facecolor(PLOT_BACKGROUND)

    cbar = fig.colorbar(
        mesh,
        ax=ax,
        boundaries=scale.bounds,
        ticks=list(scale.cbar_ticks),
        spacing="uniform",
    )
    cbar.set_ticklabels(list(scale.cbar_labels))
    cbar.ax.tick_params(labelsize=COLORBAR_TICK_FONTSIZE)
    cbar.set_label(scale.colorbar_axis_label, fontsize=COLORBAR_LABEL_FONTSIZE)

    fig.suptitle(
        f"{scale.indicator_title} — {interval_label}{region_title_suffix(region)} — "
        f"reference date {reference_date}",
        fontsize=SUPTITLE_FONTSIZE,
    )

    if save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig


def main(region: PlotRegion | None = None) -> None:
    for days in INTERVALS:
        nc_path = interval_netcdf_path(INDICES_DIR, days)
        for variable_key, scale in VARIABLE_PANELS:
            outfile = output_path_for_indicator_interval(variable_key, days, region)
            plot_single_variable_one_interval(
                nc_path,
                variable_key=variable_key,
                scale=scale,
                save_path=outfile,
                region=region,
            )
            plt.close("all")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        choices=sorted(__import__("region_subset", fromlist=["REGIONS"]).REGIONS),
        default=None,
        help="Zoom to a predefined regional subset (e.g. interior_alaska)",
    )
    args = parser.parse_args()
    main(region=parse_region_arg(args.region))
