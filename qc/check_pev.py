"""Verify the sign convention in ERA5-Land `pev`.

The ERA5 "Classic" version of the pipeline contains a comment like this:

    PET (pev) in ERA5 is usually negative because upward fluxes are negative,
    so adding pev gives the water budget.

This script checks whether the processed daily ERA5-Land `pev` file follows
that same convention.
"""

import xarray as xr

from config import daily_combined_file_for_var


def main() -> int:
    pev_path = daily_combined_file_for_var("pev")

    print(f"Opening: {pev_path}")

    with xr.open_dataset(pev_path) as ds:
        pev = ds["pev"]

        print("\nChecking pev values")
        print("-------------------")
        print(f"units: {pev.attrs.get('units', 'unknown')}")
        print(f"min:  {float(pev.min(skipna=True).item())}")
        print(f"max:  {float(pev.max(skipna=True).item())}")
        print(f"mean: {float(pev.mean(skipna=True).item())}")

        valid_count = int(pev.notnull().sum().item())
        negative_count = int((pev < 0).sum().item())
        positive_count = int((pev > 0).sum().item())
        zero_count = int((pev == 0).sum().item())

        print("\nSign counts")
        print("-----------")
        print(f"valid values: {valid_count}")
        print(f"negative:     {negative_count} ({negative_count / valid_count:.2%})")
        print(f"positive:     {positive_count} ({positive_count / valid_count:.2%})")
        print(f"zero:         {zero_count} ({zero_count / valid_count:.2%})")

        quantiles = pev.quantile([0.01, 0.05, 0.5, 0.95, 0.99], skipna=True)

        print("\nQuantiles")
        print("---------")
        for q in quantiles["quantile"].values:
            q_value = float(quantiles.sel(quantile=q).item())
            print(f"{q:>5.2f}: {q_value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
