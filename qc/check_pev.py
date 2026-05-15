"""A very very small script to verify the sign conventions in ERA5-Land `pev`

The ERA5 "Classic" version of the pipeline contains a comment like this:
# PET (pev) in ERA5 is usually negative because
# upward fluxes are negative, so adding pev gives the water budget.
"""

if __name__ == "main":
    import xarray as xr

    from config import daily_combined_file_for_var

    pev = xr.open_dataset(daily_combined_file_for_var("pev"))["pev"]

    print(float(pev.min(skipna=True)))
    print(float(pev.max(skipna=True)))
    print(float(pev.mean(skipna=True)))
