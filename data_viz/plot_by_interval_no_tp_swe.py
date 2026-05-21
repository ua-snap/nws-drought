"""Per-summary-interval grids like ``plot_by_interval`` but omitting TP and SWE maps.

Panels: Precipitation % of Normal, SWE % of Normal, SPI, SPEI, and soil moisture deficit.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_by_interval import (
    DATA_DIR,
    OUTPUT_DIR,
    SUMMARY_INTERVAL_DAYS,
    masked_for_land,
    resolve_interval_nc_path,
)
from plot_scales import (
    PNTP_SCALE,
    PNSWE_SCALE,
    SMD_SCALE,
    SPEI_USDM_SCALE,
    SPI_USDM_SCALE,
    PlotScale,
    make_colormap,
)

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
        ref_date_str = ds.attrs.get("reference_date", path.stem)
        suffix = path.stem.removeprefix("drought_indices_")
        interval_suffix = suffix.split("_")[0] if suffix else ""

        lon = ds["longitude"].values
        lat = ds["latitude"].values

        for ax, (var_key, scale) in zip(axes, VARIABLE_PANELS, strict=False):
            da = masked_for_land(ds, ds[var_key])

            cmap, norm = make_colormap(scale)
            mesh = ax.pcolormesh(
                lon,
                lat,
                da.values,
                shading="auto",
                cmap=cmap,
                norm=norm,
            )

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
        f"Drought indicators — {interval_suffix} — " f"reference date {ref_date_str}",
        fontsize=12,
    )

    if save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig


def main() -> None:
    for days in SUMMARY_INTERVAL_DAYS:
        resolved = resolve_interval_nc_path(DATA_DIR, days)
        if resolved is None:
            raise FileNotFoundError(
                f"No NetCDF found for {days}-day interval under {DATA_DIR} "
                f"(expected drought_indices_{days}day.nc or drought_indices_{days}day_*.nc)"
            )

        outfile = OUTPUT_DIR / f"drought_maps_{days}day_no_tp_swe.png"
        plot_five_variables_one_interval(resolved, save_path=outfile)
        plt.close("all")


if __name__ == "__main__":
    main()
