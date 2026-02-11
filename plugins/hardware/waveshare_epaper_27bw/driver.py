from __future__ import annotations

import importlib
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
        self._gpiozero_pin_factory: str | None = None
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
        loaded_epd_source = self._load_epd_module()
        if hasattr(loaded_epd_source, "EPD"):
            self._configure_epd_module_best_effort(loaded_epd_source)
            self._epd = loaded_epd_source.EPD()
        elif self._looks_like_epd_instance(loaded_epd_source):
            self._epd = loaded_epd_source
        else:
            raise TypeError("Waveshare driver import did not return a usable EPD module or instance.")
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
                "gpiozero_pin_factory": self._gpiozero_pin_factory or os.environ.get("GPIOZERO_PIN_FACTORY", "default"),
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

    def _configure_epd_module_best_effort(self, module: Any) -> None:
        try:
            self._configure_epd_module(module)
        except Exception:
            logger.info(
                "Unable to apply custom pin and SPI overrides for Waveshare module. Continuing with module defaults.",
                extra={"module": getattr(module, "__name__", type(module).__name__)},
            )

    def _resolve_partial_method(self) -> Any | None:
        if self._epd is None:
            return None
        for method_name in ("displayPartial", "display_partial", "DisplayPartial", "display_Partial"):
            method = getattr(self._epd, method_name, None)
            if callable(method):
                return method
        return None

    def _looks_like_epd_instance(self, candidate: Any) -> bool:
        return hasattr(candidate, "init") and hasattr(candidate, "display")

    def _load_epd_module_from_epaper(self, import_errors: list[str]) -> Any | None:
        original_pin_factory = os.environ.get("GPIOZERO_PIN_FACTORY")
        last_error: Exception | None = None

        for pin_factory in self._gpiozero_pin_factory_candidates(original_pin_factory):
            pin_factory_label = pin_factory or "default"
            self._set_gpiozero_pin_factory(pin_factory)
            self._release_gpio_resources()
            self._clear_runtime_driver_modules()
            self._epd_module_name = None

            try:
                epaper_package = importlib.import_module("epaper")
            except Exception as exc:
                last_error = exc
                import_errors.append(f"epaper(pin_factory={pin_factory_label}): {exc}")
                continue

            discovered_module = self._load_module_from_epaper_discovery(
                epaper_package=epaper_package,
                import_errors=import_errors,
            )
            if discovered_module is not None:
                self._gpiozero_pin_factory = pin_factory
                return discovered_module

            epaper_callable = getattr(epaper_package, "epaper", None)
            if not callable(epaper_callable):
                import_errors.append(f"epaper(pin_factory={pin_factory_label}): missing callable 'epaper' API")
                continue

            model_names = self._epaper_api_model_candidates(epaper_package)
            for model_name in model_names:
                try:
                    module_or_instance = epaper_callable(model_name)
                    if module_or_instance is None:
                        import_errors.append(f"epaper.epaper({model_name}, pin_factory={pin_factory_label}): returned None")
                        continue
                    self._epd_module_name = f"epaper.{model_name}"
                    self._gpiozero_pin_factory = pin_factory
                    logger.info(
                        "Loaded Waveshare backend from epaper package compatibility API.",
                        extra={"model_name": model_name, "pin_factory": pin_factory_label},
                    )
                    return module_or_instance
                except Exception as exc:
                    last_error = exc
                    detail = self._format_epaper_load_error(exc)
                    import_errors.append(f"epaper.epaper({model_name}, pin_factory={pin_factory_label}): {detail}")
                    logger.debug(
                        "Failed to load model from epaper package compatibility API.",
                        extra={"model_name": model_name, "pin_factory": pin_factory_label, "error": str(exc)},
                    )
                    self._release_gpio_resources()

            if not self._has_edge_detection_failure(import_errors):
                break

        self._set_gpiozero_pin_factory(original_pin_factory)
        if self._epd_module_name is None and last_error is not None:
            logger.debug("Unable to load Waveshare backend from epaper package.", exc_info=last_error)
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
        discovered: set[str] = set()
        package_paths = getattr(epaper_package, "__path__", None)
        if package_paths is not None:
            for module_info in pkgutil.iter_modules(package_paths):
                model_name = module_info.name
                if "2in7" not in model_name.lower():
                    continue
                if not model_name.lower().startswith("epd"):
                    continue
                discovered.add(model_name)

        if not discovered:
            discovered.update({"epd2in7", "epd2in7_V2"})

        return sorted(discovered, key=self._epaper_model_priority)

    def _epaper_model_priority(self, model_name: str) -> tuple[int, str]:
        normalized = model_name.lower()
        if normalized == "epd2in7":
            return (0, normalized)
        if normalized == "epd2in7_v2":
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

    def _epaper_api_model_candidates(self, epaper_package: Any) -> list[str]:
        discovered: set[str] = set()
        modules_api = getattr(epaper_package, "modules", None)
        if callable(modules_api):
            try:
                module_names = modules_api()
            except Exception as exc:
                logger.debug("Unable to query epaper modules() API.", extra={"error": str(exc)})
                module_names = []
            for module_name in module_names:
                if not isinstance(module_name, str):
                    continue
                lowered = module_name.lower()
                if "2in7" not in lowered:
                    continue
                if not lowered.startswith("epd"):
                    continue
                discovered.add(module_name)

        if not discovered:
            discovered.update(self._discover_epaper_model_names(epaper_package))

        discovered.update({"epd2in7"})
        return sorted(discovered, key=self._epaper_model_priority)

    def _gpiozero_pin_factory_candidates(self, current_value: str | None) -> list[str | None]:
        normalized_current = (current_value or "").strip().lower()
        candidates: list[str | None] = [current_value]
        if normalized_current != "native":
            candidates.append("native")
        if normalized_current != "rpigpio":
            candidates.append("rpigpio")

        unique: list[str | None] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = "__none__" if candidate is None else candidate.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _set_gpiozero_pin_factory(self, pin_factory: str | None) -> None:
        if pin_factory is None:
            os.environ.pop("GPIOZERO_PIN_FACTORY", None)
            return
        os.environ["GPIOZERO_PIN_FACTORY"] = pin_factory

    def _clear_runtime_driver_modules(self) -> None:
        for module_name in tuple(sys.modules):
            if module_name == "epaper" or module_name.startswith("epaper."):
                sys.modules.pop(module_name, None)
            if module_name == "gpiozero" or module_name.startswith("gpiozero."):
                sys.modules.pop(module_name, None)

    def _format_epaper_load_error(self, exc: Exception) -> str:
        detail = str(exc)
        if "Failed to add edge detection" in detail:
            return (
                f"{detail} (BUSY pin is likely in use or the active GPIO backend is unsupported. "
                "The driver retried with alternate gpiozero pin factories.)"
            )
        return detail

    def _has_edge_detection_failure(self, errors: list[str]) -> bool:
        return any("Failed to add edge detection" in error for error in errors)

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
