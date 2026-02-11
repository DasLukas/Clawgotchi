from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw

from app.application.ports.display import DisplayDriver, Frame
from app.application.command_processing import AsyncCommandQueue, CommandWorker, TickWorker
from app.application.services import (
    CommandHandlerService,
    InitializeDeviceService,
    PluginRuntime,
    PluginService,
    RenderService,
    SendCommandService,
    StateTransferService,
    StatusService,
    ThemeService,
    TickLoopService,
)
from app.config import ConfigResolver, RuntimeConfig
from app.infrastructure.database import Database
from app.infrastructure.display.dummy import DummyDisplayDriver
from app.infrastructure.hardware import DummyAudioDriver, DummyInputDriver, DummySensorDriver
from app.infrastructure.logging import configure_logging
from app.infrastructure.plugin_loader import FileSystemPluginLoader
from app.infrastructure.repositories import (
    SqlAlchemyPluginRepository,
    SqlAlchemySettingsRepository,
    SqlAlchemyStateRepository,
    SqlAlchemyThemeRepository,
)
from app.infrastructure.theme_loader import FileSystemThemeLoader
from app.infrastructure.themes.theme_loader import ThemeLoader
from config.settings import DisplaySettings

logger = logging.getLogger(__name__)


class ApplicationContainer:
    def __init__(self, config_overrides: dict | None = None) -> None:
        resolver = ConfigResolver(extra_overrides=config_overrides)
        bootstrap_config = resolver.resolve()

        self.database = Database(bootstrap_config.database_url)
        self.database.create_schema()

        self.settings_repository = SqlAlchemySettingsRepository(self.database.session_factory)
        db_config_overrides = self.settings_repository.get_prefix("config.")
        self.config: RuntimeConfig = resolver.resolve(db_overrides=db_config_overrides)

        configure_logging(self.config.log_level)
        self._ensure_directories()

        self.display_settings = DisplaySettings(
            display_type=self.config.display_type,
            display_vendor=self.config.display_vendor,
            display_rotation=self.config.display_rotation,
            display_use_partial=self.config.display_use_partial,
            display_dithering=self.config.display_dithering,
            display_debug_write_png=self.config.display_debug_write_png,
            display_debug_png_path=self.config.display_debug_png_path,
            display_spi_bus=self.config.display_spi_bus,
            display_spi_device=self.config.display_spi_device,
            display_spi_max_hz=self.config.display_spi_max_hz,
            display_gpio_dc_pin=self.config.display_gpio_dc_pin,
            display_gpio_rst_pin=self.config.display_gpio_rst_pin,
            display_gpio_busy_pin=self.config.display_gpio_busy_pin,
            display_gpio_cs_pin=self.config.display_gpio_cs_pin,
        )

        self.state_repository = SqlAlchemyStateRepository(self.database.session_factory)
        self.plugin_repository = SqlAlchemyPluginRepository(self.database.session_factory)
        self.theme_repository = SqlAlchemyThemeRepository(self.database.session_factory)

        self.plugin_loader = FileSystemPluginLoader(self.config.plugin_directory)
        self.theme_loader = FileSystemThemeLoader(self.config.theme_directory)
        self.theme_asset_loader = ThemeLoader(self.config.theme_directory)

        self.display_driver: DisplayDriver = self._create_base_display_driver()
        self.render_service = RenderService(
            theme_loader=self.theme_asset_loader,
            display_driver=self.display_driver,
            default_theme_id="default",
        )

        self.input_driver = DummyInputDriver()
        self.audio_driver = DummyAudioDriver()
        self.sensor_driver = DummySensorDriver()

        self.command_queue = AsyncCommandQueue()
        self.state_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()

        self.plugin_runtime = PluginRuntime(self.plugin_loader, self.settings_repository)

        self.command_handler_service = CommandHandlerService(
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
            plugin_runtime=self.plugin_runtime,
            render_service=self.render_service,
            lock=self.state_lock,
        )
        self.tick_loop_service = TickLoopService(
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
            plugin_runtime=self.plugin_runtime,
            render_service=self.render_service,
            lock=self.state_lock,
        )
        self.send_command_service = SendCommandService(self.command_queue, timeout_seconds=3.0)

        self.initialize_device_service = InitializeDeviceService(
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
            plugin_repository=self.plugin_repository,
            theme_repository=self.theme_repository,
            plugin_runtime=self.plugin_runtime,
        )
        self.plugin_service = PluginService(
            plugin_loader=self.plugin_loader,
            plugin_repository=self.plugin_repository,
            state_repository=self.state_repository,
            plugin_runtime=self.plugin_runtime,
            settings_repository=self.settings_repository,
        )
        self.theme_service = ThemeService(
            theme_loader=self.theme_loader,
            theme_repository=self.theme_repository,
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
        )
        self.state_transfer_service = StateTransferService(
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
            plugin_repository=self.plugin_repository,
            theme_repository=self.theme_repository,
            plugin_runtime=self.plugin_runtime,
        )
        self.status_service = StatusService(
            state_repository=self.state_repository,
            settings_repository=self.settings_repository,
            initialize_device_service=self.initialize_device_service,
        )

        self.command_worker = CommandWorker(self.command_queue, self.command_handler_service, self.stop_event)
        self.tick_worker = TickWorker(self.tick_loop_service, self.config.tick_interval_seconds, self.stop_event)
        self._tasks: list[asyncio.Task] = []
        self._hardware_status: dict[str, Any] = {
            "ok": True,
            "backend": "dummy",
            "message": "Dummy display backend is active.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ensure_directories(self) -> None:
        self.config.plugin_directory.mkdir(parents=True, exist_ok=True)
        self.config.theme_directory.mkdir(parents=True, exist_ok=True)

    async def startup(self) -> None:
        await self.plugin_service.rescan()
        self.theme_service.rescan()

        themes = self.theme_service.list_themes()
        state = self.state_repository.load_or_create(self.settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        available_theme_ids = {theme["theme_id"] for theme in themes}
        if themes and state.active_theme_id not in available_theme_ids:
            state.active_theme_id = themes[0]["theme_id"]
            self.state_repository.save_state(
                state=state,
                source="theme_auto_selected",
                command_id=None,
                events=[],
            )

        if themes and state.active_theme_id in available_theme_ids:
            self.theme_repository.activate(state.active_theme_id)

        self.refresh_display_driver(profile_id=state.hardware_profile)
        self.render_service.set_theme(state.active_theme_id)

        self._tasks = [
            asyncio.create_task(self.command_worker.run(), name="command-worker"),
            asyncio.create_task(self.tick_worker.run(), name="tick-worker"),
        ]

    async def shutdown(self) -> None:
        self.stop_event.set()

        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.plugin_runtime.shutdown()

    def refresh_display_driver(self, profile_id: str) -> dict[str, Any]:
        normalized = profile_id.strip() or "dummy"

        if normalized == "dummy":
            self._switch_display_driver(self._create_dummy_driver())
            status = self._record_hardware_status(
                ok=True,
                backend="dummy",
                message="Dummy display backend is active.",
            )
            return status

        plugin_driver = self.plugin_runtime.create_display_driver(normalized, self.display_settings)
        if plugin_driver is not None:
            try:
                self._switch_display_driver(plugin_driver)
                self._render_hardware_test_pattern(driver=plugin_driver, backend_label=normalized)
                status = self._record_hardware_status(
                    ok=True,
                    backend=normalized,
                    message="Hardware backend initialized successfully.",
                )
                return status
            except Exception as exc:
                logger.exception("Plugin display driver failed to initialize.", extra={"profile_id": normalized})
                self._switch_display_driver(self._create_dummy_driver())
                detail = str(exc).strip()
                error_message = (
                    f"Hardware backend failed. Falling back to dummy display. Details: {detail}"
                    if detail
                    else "Hardware backend failed. Falling back to dummy display."
                )
                status = self._record_hardware_status(
                    ok=False,
                    backend=normalized,
                    message=error_message,
                )
                return status

        logger.warning("Hardware profile not provided by any enabled plugin. Falling back to dummy driver.", extra={"profile_id": normalized})
        self._switch_display_driver(self._create_dummy_driver())
        status = self._record_hardware_status(
            ok=False,
            backend=normalized,
            message="Requested hardware backend is unavailable. Dummy display is active.",
        )
        return status

    def get_hardware_status(self) -> dict[str, Any]:
        return dict(self._hardware_status)

    def _create_base_display_driver(self) -> DisplayDriver:
        dummy = self._create_dummy_driver()
        dummy.init()
        return dummy

    def _create_dummy_driver(self) -> DisplayDriver:
        dummy = DummyDisplayDriver(
            rotation=self.display_settings.display_rotation,
            write_debug_png=self.display_settings.display_debug_write_png,
            debug_png_path=self.display_settings.display_debug_png_path,
        )
        return dummy

    def _switch_display_driver(self, driver: DisplayDriver) -> None:
        if driver is self.display_driver:
            return

        try:
            driver.init()
        except Exception:
            logger.exception("Display driver initialization failed before activation.")
            raise

        try:
            self.display_driver.sleep()
        except Exception:
            logger.debug("Current display driver did not sleep cleanly.", exc_info=True)

        self.display_driver = driver
        self.render_service.set_display_driver(driver)

    def _render_hardware_test_pattern(self, driver: DisplayDriver, backend_label: str) -> None:
        capabilities = driver.get_capabilities()
        frame_a = Image.new("1", (capabilities.width, capabilities.height), color=1)
        draw_a = ImageDraw.Draw(frame_a)
        draw_a.rectangle((0, 0, capabilities.width - 1, capabilities.height - 1), outline=0, width=2)
        draw_a.text((12, 12), "Clawgotchi ready", fill=0)
        draw_a.text((12, 36), backend_label, fill=0)
        draw_a.text((12, 60), "SPI online", fill=0)

        frame_b = Image.new("1", (capabilities.width, capabilities.height), color=1)
        draw_b = ImageDraw.Draw(frame_b)
        draw_b.rectangle((0, 0, capabilities.width - 1, capabilities.height - 1), outline=0, width=2)
        draw_b.text((12, 12), "Clawgotchi ready", fill=0)
        draw_b.text((12, 36), "Display test frame 2/2", fill=0)

        driver.render(Frame(image=frame_a))
        driver.render(Frame(image=frame_b))

    def _record_hardware_status(self, ok: bool, backend: str, message: str) -> dict[str, Any]:
        status = {
            "ok": ok,
            "backend": backend,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._hardware_status = status
        return status
