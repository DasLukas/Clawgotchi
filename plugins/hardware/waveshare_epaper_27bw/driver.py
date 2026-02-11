from __future__ import annotations

import importlib
import logging
from pathlib import Path
import sys
from typing import Any

from PIL import Image

from app.application.ports.display import DisplayCapabilities, DisplayDriver, Frame
from app.infrastructure.system.pi_spi import PiSpiManager, PrivilegeRequiredError
from config.settings import DisplaySettings

logger = logging.getLogger(__name__)


class WaveshareEPaper27BWDriver(DisplayDriver):
    WIDTH = 264
    HEIGHT = 176
    COLOR_THRESHOLD = 128

    def __init__(self, settings: DisplaySettings) -> None:
        self._settings = settings
        self._epd: Any | None = None
        self._epd_module_name: str | None = None
        self._supports_partial_update = False
        self._spi_device_path = Path(f"/dev/spidev{settings.display_spi_bus}.{settings.display_spi_device}")
        self._spi_manager = PiSpiManager(spi_device_path=self._spi_device_path)

    def init(self) -> None:
        if self._epd is not None:
            return

        spi_result = self._spi_manager.ensure_spi_ready()
        logger.info(
            "SPI setup check finished for Waveshare display.",
            extra={
                "running_on_pi": spi_result.running_on_raspberry_pi,
                "spi_enabled": spi_result.spi_enabled,
                "changed": spi_result.changed,
                "used_raspi_config": spi_result.used_raspi_config,
                "used_boot_config_patch": spi_result.used_boot_config_patch,
                "reboot_required": spi_result.reboot_required,
                "notes": spi_result.notes,
            },
        )

        if not spi_result.running_on_raspberry_pi:
            raise RuntimeError("Waveshare ePaper backend requires Raspberry Pi hardware.")
        if not spi_result.spi_enabled:
            raise RuntimeError("SPI is not enabled and automatic setup failed.")
        if not self._spi_device_path.exists():
            raise RuntimeError(
                f"SPI appears configured but {self._spi_device_path} is missing. Reboot Raspberry Pi and retry."
            )

        module = self._load_epd_module()
        self._configure_epd_module(module)
        self._epd = module.EPD()
        self._epd.init()
        self._supports_partial_update = self._resolve_partial_method() is not None
        self.clear()

        logger.info(
            "Initialized Waveshare 2.7 inch ePaper driver.",
            extra={
                "module": self._epd_module_name,
                "spi_device": str(self._spi_device_path),
                "spi_bus": self._settings.display_spi_bus,
                "spi_device_index": self._settings.display_spi_device,
                "spi_max_hz": self._settings.display_spi_max_hz,
                "dc_pin": self._settings.display_gpio_dc_pin,
                "rst_pin": self._settings.display_gpio_rst_pin,
                "busy_pin": self._settings.display_gpio_busy_pin,
                "cs_pin": self._settings.display_gpio_cs_pin,
                "partial_update": self._supports_partial_update,
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

    def clear(self) -> None:
        if self._epd is None:
            return
        if not hasattr(self._epd, "Clear"):
            return
        try:
            self._epd.Clear(0xFF)
        except TypeError:
            self._epd.Clear()

    def get_capabilities(self) -> DisplayCapabilities:
        return DisplayCapabilities(
            width=self.WIDTH,
            height=self.HEIGHT,
            color_mode="1bit",
            rotation=self._settings.display_rotation,
            supports_partial_update=self._supports_partial_update,
            typical_refresh_ms=1200,
        )

    def render(self, frame: Frame | Image.Image | bytes) -> None:
        if self._epd is None:
            self.init()

        payload: Any
        if isinstance(frame, Frame):
            payload = frame.image
        else:
            payload = frame

        if isinstance(payload, bytes):
            expected_length = (self.WIDTH * self.HEIGHT) // 8
            if len(payload) != expected_length:
                raise ValueError(f"Expected {expected_length} bytes for a 1-bit buffer, got {len(payload)}.")
            buffer = payload
        elif isinstance(payload, Image.Image):
            image = self._prepare_image(payload)
            buffer = self._epd.getbuffer(image)
        else:
            raise TypeError("WaveshareEPaper27BWDriver expects Frame, PIL.Image, or bytes.")

        try:
            if self._settings.display_use_partial and self._supports_partial_update:
                partial = self._resolve_partial_method()
                if partial is not None:
                    partial(buffer)
                    return
            self._epd.display(buffer)
        except Exception as exc:
            raise RuntimeError("Display refresh failed. Check BUSY pin wiring and panel model.") from exc

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        if self._settings.display_rotation:
            image = image.rotate(self._settings.display_rotation, expand=False)

        if image.size != (self.WIDTH, self.HEIGHT):
            raise ValueError(f"Frame size {image.size} does not match required {self.WIDTH}x{self.HEIGHT}.")

        grayscale = image.convert("L")
        thresholded = grayscale.point(
            lambda pixel: 255 if pixel >= self.COLOR_THRESHOLD else 0,
            mode="1",
        )
        return thresholded

    def _load_epd_module(self) -> Any:
        candidates = ("waveshare_epd.epd2in7_V2", "waveshare_epd.epd2in7")
        last_error: Exception | None = None
        import_errors: list[str] = []
        for module_name in candidates:
            try:
                module = importlib.import_module(module_name)
                self._epd_module_name = module_name
                return module
            except Exception as exc:
                last_error = exc
                import_errors.append(f"{module_name}: {exc}")
                logger.debug("Failed to import Waveshare module.", extra={"module": module_name, "error": str(exc)})

        epaper_module = self._load_epd_module_from_epaper(import_errors=import_errors)
        if epaper_module is not None:
            return epaper_module

        if isinstance(last_error, PrivilegeRequiredError):
            raise last_error
        install_hint = self._build_install_hint()
        details = "; ".join(import_errors) if import_errors else "No module candidates were importable."
        raise ImportError(f"Failed to import Waveshare Python driver package. {details}. {install_hint}") from last_error

    def _configure_epd_module(self, module: Any) -> None:
        config_module_name = f"{module.__package__}.epdconfig"
        config_module = importlib.import_module(config_module_name)

        pin_values = {
            "RST_PIN": self._settings.display_gpio_rst_pin,
            "DC_PIN": self._settings.display_gpio_dc_pin,
            "BUSY_PIN": self._settings.display_gpio_busy_pin,
            "CS_PIN": self._settings.display_gpio_cs_pin,
            "SPI_BUS": self._settings.display_spi_bus,
            "SPI_DEVICE": self._settings.display_spi_device,
            "SPI_MAX_SPEED_HZ": self._settings.display_spi_max_hz,
        }

        for key, value in pin_values.items():
            if hasattr(config_module, key):
                setattr(config_module, key, value)

        implementation = getattr(config_module, "implementation", None)
        if implementation is not None:
            for key, value in (
                ("RST_PIN", self._settings.display_gpio_rst_pin),
                ("DC_PIN", self._settings.display_gpio_dc_pin),
                ("BUSY_PIN", self._settings.display_gpio_busy_pin),
                ("CS_PIN", self._settings.display_gpio_cs_pin),
                ("spi_bus", self._settings.display_spi_bus),
                ("spi_device", self._settings.display_spi_device),
            ):
                if hasattr(implementation, key):
                    setattr(implementation, key, value)

        try:
            spidev = importlib.import_module("spidev")
            custom_spi = spidev.SpiDev()
            custom_spi.open(self._settings.display_spi_bus, self._settings.display_spi_device)
            custom_spi.max_speed_hz = self._settings.display_spi_max_hz

            if hasattr(config_module, "SPI"):
                setattr(config_module, "SPI", custom_spi)
            if implementation is not None and hasattr(implementation, "SPI"):
                setattr(implementation, "SPI", custom_spi)
        except Exception:
            logger.info("Unable to preload custom spidev object, falling back to Waveshare defaults.")

    def _resolve_partial_method(self) -> Any | None:
        if self._epd is None:
            return None
        for method_name in ("displayPartial", "display_partial", "DisplayPartial", "display_Partial"):
            method = getattr(self._epd, method_name, None)
            if callable(method):
                return method
        return None

    def _load_epd_module_from_epaper(self, import_errors: list[str]) -> Any | None:
        for model_name in ("epd2in7_V2", "epd2in7"):
            try:
                module = importlib.import_module(f"epaper.{model_name}")
                self._epd_module_name = f"epaper.{model_name}"
                logger.info(
                    "Loaded Waveshare module from epaper package module path.",
                    extra={"model_name": model_name},
                )
                return module
            except Exception as exc:
                import_errors.append(f"epaper.{model_name}: {exc}")
                logger.debug(
                    "Failed to load model from epaper package module path.",
                    extra={"model_name": model_name, "error": str(exc)},
                )

        try:
            epaper_package = importlib.import_module("epaper")
        except Exception as exc:
            import_errors.append(f"epaper: {exc}")
            return None

        for model_name in ("epd2in7_V2", "epd2in7"):
            try:
                if hasattr(epaper_package, "epaper"):
                    module = epaper_package.epaper(model_name)
                    if module is not None:
                        self._epd_module_name = f"epaper.{model_name}"
                        logger.info(
                            "Loaded Waveshare module from epaper package compatibility API.",
                            extra={"model_name": model_name},
                        )
                        return module
            except Exception as exc:
                import_errors.append(f"epaper.epaper({model_name}): {exc}")
                logger.debug(
                    "Failed to load model from epaper package compatibility API.",
                    extra={"model_name": model_name, "error": str(exc)},
                )
        return None

    def _build_install_hint(self) -> str:
        python_executable = sys.executable or "python"
        return (
            "Install dependency with: "
            f"{python_executable} -m pip install --upgrade waveshare-epaper gpiozero"
        )
