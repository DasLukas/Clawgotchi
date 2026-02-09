from __future__ import annotations

import importlib
import logging
from typing import Any

from PIL import Image

from app.application.ports.display import DisplayCapabilities, DisplayDriver, Frame
from config.settings import DisplaySettings

logger = logging.getLogger(__name__)


class WaveshareEPaper2in7Driver(DisplayDriver):
    def __init__(self, settings: DisplaySettings) -> None:
        self._settings = settings
        self._epd: Any | None = None
        self._supports_partial_update = False
        self._module_name: str | None = None

    def init(self) -> None:
        if self._epd is None:
            module = self._load_epd_module()
            self._epd = module.EPD()
            self._module_name = module.__name__

        self._epd.init()
        self._clear_display()
        self._supports_partial_update = self._has_partial_update_support()

        logger.info(
            "Initialized Waveshare 2.7 inch ePaper display",
            extra={
                "module": self._module_name,
                "partial": self._supports_partial_update,
                "rotation": self._settings.display_rotation,
            },
        )

    def sleep(self) -> None:
        if self._epd is None:
            return
        if hasattr(self._epd, "sleep"):
            self._epd.sleep()

    def wake(self) -> None:
        if self._epd is None:
            self.init()
            return
        self._epd.init()

    def get_capabilities(self) -> DisplayCapabilities:
        return DisplayCapabilities(
            width=264,
            height=176,
            color_mode="1bit",
            rotation=self._settings.display_rotation,
            supports_partial_update=self._supports_partial_update,
            typical_refresh_ms=1200,
        )

    def render(self, frame: Frame) -> None:
        if self._epd is None:
            self.init()

        if not isinstance(frame.image, Image.Image):
            raise TypeError("WaveshareEPaper2in7Driver expects Frame.image to be a PIL Image.")

        dither_mode = Image.FLOYDSTEINBERG if self._settings.display_dithering else Image.NONE
        image = frame.image.convert("1", dither=dither_mode)

        if self._settings.display_rotation:
            image = image.rotate(self._settings.display_rotation, expand=False)

        capabilities = self.get_capabilities()
        if image.size != (capabilities.width, capabilities.height):
            raise ValueError(
                f"Frame size {image.size} does not match display size "
                f"{capabilities.width}x{capabilities.height}."
            )

        buffer = self._epd.getbuffer(image)

        if self._settings.display_use_partial and self._supports_partial_update:
            partial_method = self._resolve_partial_method()
            if partial_method is not None:
                partial_method(buffer)
                return

        self._epd.display(buffer)

    def _load_epd_module(self) -> Any:
        candidates = ("waveshare_epd.epd2in7_V2", "waveshare_epd.epd2in7")
        last_error: Exception | None = None
        gpio_busy_detected = False

        for module_name in candidates:
            try:
                return importlib.import_module(module_name)
            except Exception as exc:
                last_error = exc
                if "GPIO busy" in str(exc):
                    gpio_busy_detected = True
                logger.debug("Failed to import Waveshare module", extra={"module": module_name, "error": str(exc)})

        if last_error is not None:
            if gpio_busy_detected:
                raise ImportError(
                    "Unable to import Waveshare 2.7 inch EPD module because GPIO lines are busy."
                ) from last_error
            raise ImportError("Unable to import Waveshare 2.7 inch EPD module.") from last_error
        raise ImportError("Unable to import Waveshare 2.7 inch EPD module.")

    def _clear_display(self) -> None:
        if self._epd is None:
            return
        if not hasattr(self._epd, "Clear"):
            return

        try:
            self._epd.Clear(0xFF)
        except TypeError:
            self._epd.Clear()

    def _resolve_partial_method(self) -> Any | None:
        if self._epd is None:
            return None
        for method_name in ("displayPartial", "display_partial", "DisplayPartial", "display_Partial"):
            method = getattr(self._epd, method_name, None)
            if callable(method):
                return method
        return None

    def _has_partial_update_support(self) -> bool:
        return self._resolve_partial_method() is not None
