from __future__ import annotations

import logging

from app.application.ports.display import DisplayDriver
from app.infrastructure.display.dummy import DummyDisplayDriver
from app.infrastructure.display.waveshare_epaper_2in7 import WaveshareEPaper2in7Driver
from config.settings import DisplaySettings

logger = logging.getLogger(__name__)


def create_display_driver(settings: DisplaySettings) -> DisplayDriver:
    if settings.display_type.lower() == "epaper_hat" and settings.display_vendor.lower() == "waveshare":
        try:
            driver = WaveshareEPaper2in7Driver(settings=settings)
            driver.init()
            return driver
        except Exception:
            logger.exception("Falling back to DummyDisplayDriver because Waveshare initialization failed.")

    dummy = DummyDisplayDriver(
        rotation=settings.display_rotation,
        write_debug_png=settings.display_debug_write_png,
        debug_png_path=settings.display_debug_png_path,
    )
    dummy.init()
    return dummy
