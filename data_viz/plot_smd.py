from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr

from plot_scales import SMD_SCALE, make_colormap

data_dir = Path("drought_outputs")
OUTPUT_DIR = Path(__file__).resolve().parent

all_files = [
    Path("drought_outputs/drought_indices_7day.nc"),
    Path("drought_outputs/drought_indices_30day.nc"),
    Path("drought_outputs/drought_indices_60day.nc"),
    Path("drought_outputs/drought_indices_90day.nc"),
    Path("drought_outputs/drought_indices_180day.nc"),
    Path("drought_outputs/drought_indices_365day.nc"),
]

variable_key = "smd"

scale = SMD_SCALE
bounds = scale.bounds
cbar_labels = scale.cbar_labels
cbar_ticks = scale.cbar_ticks
cmap, norm = make_colormap(scale)


def plot_variable_across_files(
    paths: list[str | Path],
    figsize_per_panel: tuple[float, float] = (5.5, 4.0),
    save_path: str | Path | None = None,
) -> plt.Figure:
    """Compare the same variable across multiple NetCDF files."""

    ncols = 3
    nrows = 2

    #
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(figsize_per_panel[0] * ncols, figsize_per_panel[1] * nrows),
        constrained_layout=True,
        squeeze=False,
        sharex=True,
        sharey=True,
    )

    #
    opened: list[tuple[Path, xr.Dataset]] = []

    for path in paths:
        p = Path(path)
        ds = xr.open_dataset(p)
        opened.append((p, ds))

    ref_date = ds.attrs["reference_date"]

    mesh = None

    for ax, (path, ds) in zip(axes.flat, opened, strict=False):
        da = ds[variable_key]

        lon = ds["longitude"].values
        lat = ds["latitude"].values

        mesh = ax.pcolormesh(
            lon,
            lat,
            da.values,
            shading="auto",
            cmap=cmap,
            norm=norm,
        )

        ax.set_title(Path(path).stem.split("_")[-1])
        ax.label_outer()
        ax.set_facecolor(scale.mask_color)

    fig.supxlabel("Longitude")
    fig.supylabel("Latitude")
    if mesh is None:
        raise ValueError("No input files were provided.")

    # Colorbar with categorical labels
    cbar = fig.colorbar(
        mesh,
        ax=axes.ravel().tolist(),
        boundaries=bounds,
        ticks=cbar_ticks,
        spacing="uniform",
    )

    cbar.set_ticklabels(cbar_labels)
    cbar.set_label(scale.colorbar_axis_label)

    fig.suptitle(f"{scale.indicator_title} -- Analysis Date {ref_date}", fontsize=12)

    if save_path is not None:
        fig.savefig(save_path, dpi=200, bbox_inches="tight")


plot_variable_across_files(all_files, save_path=OUTPUT_DIR / "smd.png")
