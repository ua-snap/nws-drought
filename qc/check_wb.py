"""Check whether shifted water balance remains valid for SPEI.

SPEI is computed using:

    wb = (tp + pev) + WATER_BUDGET_OFFSET_M

Some distribution choices for SPEI (e.g., Gamma) require strictly
positive inputs. This script reports whether the shifted (and interval-averaged)
water balance contains values <= 0, which would be problematic for those cases.
"""

import xarray as xr

from config import INTERVALS, WATER_BUDGET_OFFSET_M, daily_combined_file_for_var


def main() -> int:
    tp_path = daily_combined_file_for_var("tp")
    pev_path = daily_combined_file_for_var("pev")

    print(f"Opening tp:  {tp_path}")
    print(f"Opening pev: {pev_path}")

    with xr.open_dataset(tp_path) as tp_ds, xr.open_dataset(pev_path) as pev_ds:
        tp = tp_ds["tp"]
        pev = pev_ds["pev"]

        wb = tp + pev
        wb_shifted = wb + WATER_BUDGET_OFFSET_M

        print("\nRaw water balance")
        print("-----------------")
        print(f"min:  {float(wb.min(skipna=True).item())}")
        print(f"max:  {float(wb.max(skipna=True).item())}")
        print(f"mean: {float(wb.mean(skipna=True).item())}")

        print("\nShifted water balance")
        print("---------------------")
        print(f"offset: {WATER_BUDGET_OFFSET_M}")
        print(f"min:    {float(wb_shifted.min(skipna=True).item())}")
        print(f"max:    {float(wb_shifted.max(skipna=True).item())}")
        print(f"mean:   {float(wb_shifted.mean(skipna=True).item())}")

        print("\nInterval checks")
        print("---------------")

        for interval in INTERVALS:
            wb_i = wb_shifted.rolling(valid_time=interval).mean(
                skipna=False,
                keep_attrs=True,
            )

            valid_count = int(wb_i.notnull().sum().item())
            nonpositive_count = int((wb_i <= 0).sum().item())
            nan_count = int(wb_i.isnull().sum().item())

            print(f"\ninterval={interval}")
            print(f"min:          {float(wb_i.min(skipna=True).item())}")
            print(f"max:          {float(wb_i.max(skipna=True).item())}")
            print(f"valid values: {valid_count}")
            print(f"<= 0 values:  {nonpositive_count}")
            print(f"NaN values:   {nan_count}")

            if valid_count > 0:
                print(f"<= 0 fraction of valid: {nonpositive_count / valid_count:.4%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
