"""Plots all drought-indicator variables by summary interval (one figure per interval).

Contrast with plot_<variable>.py, which compares one variable across intervals.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_scales import (
    PNTP_SCALE,
    PNSWE_SCALE,
    SMD_SCALE,
    SPEI_USDM_SCALE,
    SPI_USDM_SCALE,
    SWE_SCALE,
    TP_SCALE,
    PlotScale,
    make_colormap,
)

# Matches the per-variable scripts and README intervals (excluding 14-day configs).
SUMMARY_INTERVAL_DAYS = (7, 30, 60, 90, 180, 365)

DATA_DIR = Path("drought_outputs")
OUTPUT_DIR = Path(__file__).resolve().parent

# Order matches README indicator list (variable key, discrete color scale).
VARIABLE_PANELS: tuple[tuple[str, PlotScale], ...] = (
    ("tp", TP_SCALE),
    ("pntp", PNTP_SCALE),
    ("swe", SWE_SCALE),
    ("pnswe", PNSWE_SCALE),
    ("spi", SPI_USDM_SCALE),
    ("spei", SPEI_USDM_SCALE),
    ("smd", SMD_SCALE),
)


def resolve_interval_nc_path(data_dir: Path, days: int) -> Path | None:
    """Locate the NetCDF for a summary interval (dated or plain filename).

    `pipeline_run.py` writes drought_indices_<n>day_<YYYY_MM_DD>.nc; the
    per-variable plotting scripts use drought_indices_<n>day.nc.
    """

    bare = data_dir / f"drought_indices_{days}day.nc"
    if bare.exists():
        return bare
    dated = sorted(data_dir.glob(f"drought_indices_{days}day_*.nc"))
    return dated[-1] if dated else None


def masked_for_land(ds: xr.Dataset, da: xr.DataArray) -> xr.DataArray:
    """Mask ocean/non-land consistently with existing variable plots."""

    return da.where(ds["smd"].notnull())


def plot_all_variables_one_interval(
    nc_path: str | Path,
    figsize: tuple[float, float] = (16, 12),
    save_path: str | Path | None = None,
) -> plt.Figure:
    """One figure showing every indicator grid for one summary-interval file."""

    path = Path(nc_path)

    fig, axes_grid = plt.subplots(
        nrows=3,
        ncols=3,
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
        f"Drought indicators — {interval_suffix} — reference date {ref_date_str}",
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

        outfile = OUTPUT_DIR / f"drought_maps_{days}day.png"
        plot_all_variables_one_interval(resolved, save_path=outfile)
        plt.close("all")


if __name__ == "__main__":
    main()
