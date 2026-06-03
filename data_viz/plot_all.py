"""Generate all drought map figures (full domain and regional subsets)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from region_subset import REGIONS

DATA_VIZ_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATA_VIZ_DIR.parent

PLOT_SCRIPTS = (
    "plot_tp.py",
    "plot_pntp.py",
    "plot_swe.py",
    "plot_pnswe.py",
    "plot_spi.py",
    "plot_spei.py",
    "plot_smd.py",
    "plot_by_interval.py",
    "plot_by_interval_no_tp_swe.py",
    "plot_single_panels.py",
)


def resolve_scopes(
    *,
    region: str | None = None,
    full_domain_only: bool = False,
    regions_only: bool = False,
    include_full_domain: bool = False,
) -> list[str | None]:
    """Return geographic scopes to plot (``None`` means full domain)."""

    if region is not None:
        scopes: list[str | None] = []
        if include_full_domain:
            scopes.append(None)
        scopes.append(region)
        return scopes

    if full_domain_only:
        return [None]
    if regions_only:
        return list(sorted(REGIONS))
    return [None, *sorted(REGIONS)]


def run_plot_script(script: str, region: str | None) -> None:
    cmd = [sys.executable, str(DATA_VIZ_DIR / script)]
    if region is not None:
        cmd.extend(["--region", region])
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def run_all_plots(
    *,
    region: str | None = None,
    full_domain_only: bool = False,
    regions_only: bool = False,
    include_full_domain: bool = False,
) -> None:
    scopes = resolve_scopes(
        region=region,
        full_domain_only=full_domain_only,
        regions_only=regions_only,
        include_full_domain=include_full_domain,
    )
    for scope in scopes:
        for script in PLOT_SCRIPTS:
            run_plot_script(script, scope)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run every data_viz plotting script. "
            "By default, generates full-domain figures plus all regional subsets."
        )
    )
    parser.add_argument(
        "--region",
        choices=sorted(REGIONS),
        default=None,
        help="Limit output to one regional subset",
    )
    parser.add_argument(
        "--full-domain-only",
        action="store_true",
        help="Skip regional subsets",
    )
    parser.add_argument(
        "--regions-only",
        action="store_true",
        help="Skip full-domain plots",
    )
    parser.add_argument(
        "--include-full-domain",
        action="store_true",
        help="With --region, also generate full-domain figures",
    )
    args = parser.parse_args()

    if args.full_domain_only and args.regions_only:
        parser.error("Cannot use --full-domain-only and --regions-only together.")
    if args.include_full_domain and args.region is None:
        parser.error("--include-full-domain requires --region.")

    run_all_plots(
        region=args.region,
        full_domain_only=args.full_domain_only,
        regions_only=args.regions_only,
        include_full_domain=args.include_full_domain,
    )


if __name__ == "__main__":
    main()
