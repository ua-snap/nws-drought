"""Per-summary-interval grids like ``plot_by_interval`` but omitting TP and SWE maps.

Panels: Precipitation % of Normal, SWE % of Normal, SPI, SPEI, and soil moisture deficit.
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_common import (
    INDICES_DIR,
    INTERVALS,
    interval_netcdf_path,
    masked_for_land,
    output_path_for_interval_maps,
    parse_drought_indices_path,
    parse_region_arg,
)
from plot_communities import add_communities_to_axes
from plot_scales import (
    PNTP_SCALE,
    PNSWE_SCALE,
    SMD_SCALE,
    SPEI_USDM_SCALE,
    SPI_USDM_SCALE,
    PlotScale,
    make_colormap,
)
from region_subset import PlotRegion, region_title_suffix, subset_for_pcolormesh

VARIABLE_PANELS: tuple[tuple[str, PlotScale], ...] = (
    ("pntp", PNTP_SCALE),
    ("pnswe", PNSWE_SCALE),
    ("spi", SPI_USDM_SCALE),
    ("spei", SPEI_USDM_SCALE),
    ("smd", SMD_SCALE),
)


def plot_five_variables_one_interval(
    nc_path: str | Path,
    figsize: tuple[float, float] = (16, 10),
    save_path: str | Path | None = None,
    region: PlotRegion | None = None,
) -> plt.Figure:
    """One figure with five anomaly / normalized indicators for one interval file."""

    path = Path(nc_path)

    nrows = 2
    ncols = 3
    fig, axes_grid = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=figsize,
        constrained_layout=True,
        squeeze=False,
        sharex=True,
        sharey=True,
    )
    axes = axes_grid.ravel()
    fig.patch.set_facecolor("white")

    for ax_unused in axes[len(VARIABLE_PANELS) :]:
        ax_unused.axis("off")

    with xr.open_dataset(path) as ds:
        _, reference_date, interval_label = parse_drought_indices_path(path)

        for ax, (var_key, scale) in zip(axes, VARIABLE_PANELS, strict=False):
            da = masked_for_land(ds, ds[var_key])
            lon, lat, values = subset_for_pcolormesh(ds, da, region)

            cmap, norm = make_colormap(scale)
            mesh = ax.pcolormesh(
                lon,
                lat,
                values,
                shading="auto",
                cmap=cmap,
                norm=norm,
            )
            add_communities_to_axes(ax, region, lon, lat)

            ax.set_title(scale.panel_title, fontsize=10)
            ax.label_outer()
            ax.set_facecolor(scale.mask_color)

            cbar = fig.colorbar(
                mesh,
                ax=ax,
                boundaries=scale.bounds,
                ticks=list(scale.cbar_ticks),
                spacing="uniform",
            )
            cbar.set_ticklabels(list(scale.cbar_labels))
            cbar.ax.tick_params(labelsize=7)
            cbar.set_label(scale.colorbar_axis_label, fontsize=9)

    fig.supxlabel("Longitude")
    fig.supylabel("Latitude")
    fig.suptitle(
        f"Drought indicators — {interval_label}{region_title_suffix(region)} — "
        f"reference date {reference_date}",
        fontsize=12,
    )

    if save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig


def main(region: PlotRegion | None = None) -> None:
    for days in INTERVALS:
        nc_path = interval_netcdf_path(INDICES_DIR, days)
        outfile = output_path_for_interval_maps(days, region, five_panel=True)
        plot_five_variables_one_interval(nc_path, save_path=outfile, region=region)
        plt.close("all")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        choices=sorted(__import__("region_subset", fromlist=["REGIONS"]).REGIONS),
        default=None,
        help="Zoom to a predefined subset (e.g. interior_alaska for 64×64 cells)",
    )
    args = parser.parse_args()
    main(region=parse_region_arg(args.region))
