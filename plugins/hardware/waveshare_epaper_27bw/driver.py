from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
import pkgutil
import pwd
import sys
from typing import Any
import warnings

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

        self._release_gpio_resources()

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

        self._validate_device_permissions()
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
        try:
            if self._epd is not None and hasattr(self._epd, "sleep"):
                self._epd.sleep()
        finally:
            self._release_gpio_resources()
            self._epd = None
            self._supports_partial_update = False

    def wake(self) -> None:
        self.init()

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
        try:
            epaper_package = importlib.import_module("epaper")
        except Exception as exc:
            import_errors.append(f"epaper: {exc}")
            return None

        discovered_module = self._load_module_from_epaper_discovery(
            epaper_package=epaper_package,
            import_errors=import_errors,
        )
        if discovered_module is not None:
            return discovered_module

        epaper_callable = getattr(epaper_package, "epaper", None)
        if not callable(epaper_callable):
            import_errors.append("epaper: missing callable 'epaper' API")
            return None

        api_kwargs = self._build_epaper_api_kwargs(epaper_callable)
        for model_name in self._epaper_api_model_candidates():
            try:
                module = epaper_callable(model_name, **api_kwargs)
                if module is not None:
                    self._epd_module_name = f"epaper.{model_name}"
                    logger.info(
                        "Loaded Waveshare module from epaper package compatibility API.",
                        extra={"model_name": model_name},
                    )
                    return module
            except Exception as exc:
                detail = str(exc)
                if "Failed to add edge detection" in detail:
                    detail = (
                        f"{detail} (BUSY pin is likely in use by another process. "
                        "Stop other display processes and retry.)"
                    )
                import_errors.append(f"epaper.epaper({model_name}): {detail}")
                logger.debug(
                    "Failed to load model from epaper package compatibility API.",
                    extra={"model_name": model_name, "error": str(exc)},
                )
                self._release_gpio_resources()
        return None

    def _load_module_from_epaper_discovery(self, epaper_package: Any, import_errors: list[str]) -> Any | None:
        model_names = self._discover_epaper_model_names(epaper_package)
        for model_name in model_names:
            module_name = f"epaper.{model_name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                import_errors.append(f"{module_name}: {exc}")
                logger.debug(
                    "Failed to import discovered epaper module.",
                    extra={"module": module_name, "error": str(exc)},
                )
                continue

            if not hasattr(module, "EPD"):
                import_errors.append(f"{module_name}: missing EPD class")
                continue

            if not self._module_matches_target_resolution(module):
                width = getattr(module, "EPD_WIDTH", "unknown")
                height = getattr(module, "EPD_HEIGHT", "unknown")
                import_errors.append(
                    f"{module_name}: unsupported panel size {width}x{height}"
                )
                continue

            self._epd_module_name = module_name
            logger.info(
                "Loaded Waveshare module from discovered epaper module path.",
                extra={"model_name": model_name},
            )
            return module
        return None

    def _discover_epaper_model_names(self, epaper_package: Any) -> list[str]:
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

        return sorted(discovered, key=self._epaper_model_priority)

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
        return {width, height} == {self.WIDTH, self.HEIGHT}

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
        required_paths = [
            (self._spi_device_path, "spi"),
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

    def _build_install_hint(self) -> str:
        python_executable = sys.executable or "python"
        return (
            "Install dependency with: "
            f"{python_executable} -m pip install --upgrade waveshare-epaper gpiozero"
        )
