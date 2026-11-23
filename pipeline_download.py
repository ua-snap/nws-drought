"""Download the necessary recent ERA5-Land data for drought indicator computation."""

import logging
import time

from download_helpers import download_recurring_era5_land
from file_helpers import setup_logging

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    setup_logging()
    start = time.monotonic()
    download_recurring_era5_land()
    logger.info(
        "Pipeline download script completed in %.1f minutes.",
        (time.monotonic() - start) / 60,
    )
