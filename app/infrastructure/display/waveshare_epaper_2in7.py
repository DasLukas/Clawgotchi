from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
import pwd
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
            self._release_gpio_resources()
            self._validate_device_permissions()
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
        try:
            if self._epd is not None and hasattr(self._epd, "sleep"):
                self._epd.sleep()
        finally:
            self._release_gpio_resources()
            self._epd = None
            self._supports_partial_update = False

    def wake(self) -> None:
        if self._epd is None:
            self.init()
            return
        self._epd.init()

    def clear(self) -> None:
        self._clear_display()

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

        for module_name in ("epaper.epd2in7_V2", "epaper.epd2in7"):
            try:
                return importlib.import_module(module_name)
            except Exception as exc:
                last_error = exc
                if "GPIO busy" in str(exc):
                    gpio_busy_detected = True
                logger.debug("Failed to import Waveshare module", extra={"module": module_name, "error": str(exc)})

        try:
            epaper_package = importlib.import_module("epaper")
            if hasattr(epaper_package, "epaper"):
                for model_name in ("epd2in7_V2", "epd2in7"):
                    try:
                        module = epaper_package.epaper(model_name)
                        if module is not None:
                            return module
                    except Exception as exc:
                        last_error = exc
                        if "GPIO busy" in str(exc):
                            gpio_busy_detected = True
                        logger.debug(
                            "Failed to load Waveshare module via epaper compatibility API",
                            extra={"model": model_name, "error": str(exc)},
                        )
        except Exception as exc:
            last_error = exc
            logger.debug("Failed to import epaper package", extra={"error": str(exc)})

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

    def _release_gpio_resources(self) -> None:
        self._cleanup_gpiozero_pin_factory()
        self._cleanup_rpi_gpio()

    def _cleanup_gpiozero_pin_factory(self) -> None:
        try:
            gpiozero_module = importlib.import_module("gpiozero")
            device_class = getattr(gpiozero_module, "Device", None)
            if device_class is None:
                return
            pin_factory = getattr(device_class, "pin_factory", None)
            if pin_factory is not None and hasattr(pin_factory, "close"):
                pin_factory.close()
                setattr(device_class, "pin_factory", None)
        except Exception:
            logger.debug("Unable to close gpiozero pin factory during display cleanup.", exc_info=True)

    def _cleanup_rpi_gpio(self) -> None:
        try:
            gpio_module = importlib.import_module("RPi.GPIO")
            if hasattr(gpio_module, "getmode") and gpio_module.getmode() is None:
                return
            pins = sorted(
                {
                    self._settings.display_gpio_busy_pin,
                    self._settings.display_gpio_rst_pin,
                    self._settings.display_gpio_dc_pin,
                    self._settings.display_gpio_cs_pin,
                }
            )
            gpio_module.cleanup(pins)
        except Exception:
            logger.debug("Unable to cleanup RPi.GPIO pins during display cleanup.", exc_info=True)

    def _validate_device_permissions(self) -> None:
        spi_path = Path(f"/dev/spidev{self._settings.display_spi_bus}.{self._settings.display_spi_device}")
        required_paths = [
            (spi_path, "spi"),
            (Path("/dev/gpiomem"), "gpio"),
            (Path("/dev/gpiochip0"), "gpio"),
        ]
        blocked: list[tuple[Path, str]] = []
        for device_path, group_name in required_paths:
            if device_path.exists() and not os.access(device_path, os.R_OK | os.W_OK):
                blocked.append((device_path, group_name))

        if not blocked:
            return

        username = self._current_username()
        blocked_devices = ", ".join(str(path) for path, _ in blocked)
        missing_groups = ", ".join(sorted({group for _, group in blocked}))
        raise PermissionError(
            f"User '{username}' cannot access {blocked_devices}. "
            f"Add the user to Linux group(s) [{missing_groups}] and restart clawgotchi.service."
        )

    def _current_username(self) -> str:
        try:
            return pwd.getpwuid(os.geteuid()).pw_name
        except Exception:
            return str(os.geteuid())
