"""Re-export ERA5-Land variable registry from the shared package."""

from nws_drought.era5_land.registry import VARIABLE_REGISTRY

__all__ = ["VARIABLE_REGISTRY"]
