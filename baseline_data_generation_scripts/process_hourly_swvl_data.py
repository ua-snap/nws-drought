"""Process hourly soil moisture layer 1 and layer 2 data to daily frequency. Layers 1 and 2 are combined using weights of 0.25 for layer 1 and 0.75 for layer 2."""

import argparse
import os
from pathlib import Path

import xarray as xr

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-d_layer_1",
        dest="data_dir_layer_1",
        type=str,
        help="Directory of hourly ERA5-Land swvl level 1 .nc files.",
    )
    parser.add_argument(
        "-d_layer_2",
        dest="data_dir_layer_2",
        type=str,
        help="Directory of hourly ERA5-Land swvl level 2 .nc files.",
    )
    args = parser.parse_args()
    data_dir_layer_1 = Path(args.data_dir_layer_1)
    data_dir_layer_2 = Path(args.data_dir_layer_2)

    level1_fps = sorted(list(data_dir_layer_1.glob("*.nc")))
    level2_fps = sorted(list(data_dir_layer_2.glob("*.nc")))

    if not level1_fps:
        raise FileNotFoundError(
            f"No .nc files found in layer 1 directory: {data_dir_layer_1}"
        )
    if not level2_fps:
        raise FileNotFoundError(
            f"No .nc files found in layer 2 directory: {data_dir_layer_2}"
        )
    if len(level1_fps) != len(level2_fps):
        raise ValueError(
            f"Layer file count mismatch: layer1={len(level1_fps)} layer2={len(level2_fps)}"
        )

    running_sum = None
    running_count = None

    for fp1, fp2 in zip(level1_fps, level2_fps):
        with (
            xr.open_dataset(fp1, engine="h5netcdf") as ds1,
            xr.open_dataset(fp2, engine="h5netcdf") as ds2,
        ):
            ds1, ds2 = xr.align(ds1, ds2, join="exact")
            swvl = (ds1["swvl1"] * 0.25) + (ds2["swvl2"] * 0.75)

            # Accumulate hourly sums and counts by day-of-year to preserve
            # the original mean-over-all-hourly-timestamps behavior.
            doy_sum = swvl.groupby("time.dayofyear").sum(dim="time", skipna=True).load()
            doy_count = swvl.groupby("time.dayofyear").count(dim="time").load()

        if running_sum is None:
            running_sum = doy_sum
            running_count = doy_count
        else:
            running_sum = running_sum + doy_sum
            running_count = running_count + doy_count

    clim_da = (running_sum / running_count).rename({"dayofyear": "time"})
    clim_da.name = "swvl"

    out_dir = Path(os.environ.get("NWS_DROUGHT_CLIM_DIR", Path.cwd()))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_fp = out_dir / "era5_daily_swvl_1981_2020.nc"
    clim_da.to_dataset().to_netcdf(out_fp)
