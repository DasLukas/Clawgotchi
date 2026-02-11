from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
import pkgutil
import pwd
from typing import Any
import warnings

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
            discovered = self._load_epaper_module_by_discovery(epaper_package)
            if discovered is not None:
                return discovered
            epaper_callable = getattr(epaper_package, "epaper", None)
            if callable(epaper_callable):
                kwargs = self._build_epaper_api_kwargs(epaper_callable)
                for model_name in self._epaper_api_model_candidates():
                    try:
                        module = epaper_callable(model_name, **kwargs)
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
                        self._release_gpio_resources()
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

    def _load_epaper_module_by_discovery(self, epaper_package: Any) -> Any | None:
        discovered: set[str] = {"epd2in7_V2", "epd2in7"}
        package_paths = getattr(epaper_package, "__path__", None)
        if package_paths is not None:
            for module_info in pkgutil.iter_modules(package_paths):
                model_name = module_info.name
                if "2in7" not in model_name.lower():
                    continue
                if not model_name.lower().startswith("epd"):
                    continue
                discovered.add(model_name)

        for model_name in sorted(discovered, key=self._epaper_model_priority):
            module_name = f"epaper.{model_name}"
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            if not hasattr(module, "EPD"):
                continue
            if self._module_matches_target_resolution(module):
                return module
        return None

    def _epaper_model_priority(self, model_name: str) -> tuple[int, str]:
        normalized = model_name.lower()
        if normalized == "epd2in7_v2":
            return (0, normalized)
        if normalized == "epd2in7":
            return (1, normalized)
        if "2in7" in normalized and "v2" in normalized:
            return (2, normalized)
        if "2in7" in normalized:
            return (3, normalized)
        return (99, normalized)

    def _module_matches_target_resolution(self, module: Any) -> bool:
        width = getattr(module, "EPD_WIDTH", None)
        height = getattr(module, "EPD_HEIGHT", None)
        if not isinstance(width, int) or not isinstance(height, int):
            return True
        return {width, height} == {264, 176}

    def _build_epaper_api_kwargs(self, epaper_callable: Any) -> dict[str, Any]:
        parameter_names: set[str] = set()
        has_var_kwargs = False
        try:
            signature = inspect.signature(epaper_callable)
            parameter_names = set(signature.parameters)
            has_var_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            )
        except Exception:
            parameter_names = set()

        def _supports(name: str) -> bool:
            return has_var_kwargs or name in parameter_names

        kwargs: dict[str, Any] = {}
        pin_candidates: tuple[tuple[str, Any], ...] = (
            ("busy", self._settings.display_gpio_busy_pin),
            ("busy_pin", self._settings.display_gpio_busy_pin),
            ("busy_gpio", self._settings.display_gpio_busy_pin),
            ("gpio_busy", self._settings.display_gpio_busy_pin),
            ("dc", self._settings.display_gpio_dc_pin),
            ("dc_pin", self._settings.display_gpio_dc_pin),
            ("dc_gpio", self._settings.display_gpio_dc_pin),
            ("gpio_dc", self._settings.display_gpio_dc_pin),
            ("rst", self._settings.display_gpio_rst_pin),
            ("reset", self._settings.display_gpio_rst_pin),
            ("rst_pin", self._settings.display_gpio_rst_pin),
            ("reset_pin", self._settings.display_gpio_rst_pin),
            ("rst_gpio", self._settings.display_gpio_rst_pin),
            ("gpio_rst", self._settings.display_gpio_rst_pin),
            ("cs", self._settings.display_gpio_cs_pin),
            ("cs_pin", self._settings.display_gpio_cs_pin),
            ("cs_gpio", self._settings.display_gpio_cs_pin),
            ("gpio_cs", self._settings.display_gpio_cs_pin),
            ("spi_bus", self._settings.display_spi_bus),
            ("spi_device", self._settings.display_spi_device),
            ("bus", self._settings.display_spi_bus),
            ("device", self._settings.display_spi_device),
        )
        for key, value in pin_candidates:
            if _supports(key):
                kwargs[key] = value

        mode_candidates: tuple[tuple[str, Any], ...] = (
            ("gpio_mode", "BCM"),
            ("pin_mode", "BCM"),
            ("mode", "BCM"),
            ("numbering", "BCM"),
            ("use_bcm", True),
            ("board", False),
        )
        for key, value in mode_candidates:
            if _supports(key):
                kwargs[key] = value

        return kwargs

    def _epaper_api_model_candidates(self) -> list[str]:
        candidates = [
            "epd2in7_V2",
            "epd2in7",
            "epd2in7v2",
            "epd_2in7_V2",
            "epd_2in7",
            "2in7_V2",
            "2in7",
        ]
        unique: list[str] = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return unique

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
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="No channels have been set up yet - nothing to clean up!",
                    category=RuntimeWarning,
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
