from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import time
from typing import Any

from PIL import Image, ImageDraw

from app.application.input.router import InputRouter
from app.application.ports.display import DisplayCapabilities, DisplayDriver
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
from app.application.ui.menu_controller import MenuController
from app.config import ConfigResolver, RuntimeConfig
from app.infrastructure.database import Database
from app.infrastructure.display.dummy import DummyDisplayDriver
from app.infrastructure.display.sinks import DisplayDriverSink
from app.infrastructure.hardware import DummyAudioDriver, DummyInputDriver, DummySensorDriver
from app.infrastructure.input.gpio_buttons import GPIOButtonDriver
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
from app.domain.models.pet_state import PetState
from app.domain.ui.input import ButtonId, InputEvent
from config.settings import DisplaySettings
from core.display_manager import DisplayManager
from core.framebuffer import FrameBuffer1Bit

logger = logging.getLogger(__name__)


def _normalize_hardware_profile_id(profile_id: str, default: str = "dummy") -> str:
    normalized = profile_id.strip()
    if not normalized:
        return default
    return normalized


class ApplicationContainer:
    DEFAULT_CAPABILITIES = DisplayCapabilities(
        width=264,
        height=176,
        color_mode="1bit",
        rotation=0,
        supports_partial_update=False,
        typical_refresh_ms=1200,
    )

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

        self.display_manager = DisplayManager()
        self._display_update_condition = asyncio.Condition()
        self._display_update_loop: asyncio.AbstractEventLoop | None = None
        self.display_manager.subscribe(self._on_display_push)

        self.input_router = InputRouter(max_queue_size=512)
        self.menu_controller = MenuController.create_default(
            action_dispatcher=lambda _action_id: None,
            indicator_provider=self._menu_indicators,
        )

        self.display_driver: DisplayDriver = self._create_base_display_driver()
        self.active_display_capabilities = self._safe_get_capabilities(self.display_driver)
        self.framebuffer = FrameBuffer1Bit(
            width=self.active_display_capabilities.width,
            height=self.active_display_capabilities.height,
        )
        self._latest_display_version = self.framebuffer.version
        self._latest_display_updated_at_ms = self.framebuffer.updated_at_ms
        self.display_manager.set_sinks([DisplayDriverSink(self.display_driver)])
        self.render_service = RenderService(
            theme_loader=self.theme_asset_loader,
            framebuffer=self.framebuffer,
            display_manager=self.display_manager,
            display_capabilities=self.active_display_capabilities,
            input_router=self.input_router,
            menu_controller=self.menu_controller,
            default_theme_id="default",
        )

        self.gpio_button_driver = GPIOButtonDriver(
            router=self.input_router,
            pin_mapping={
                ButtonId.NEXT: self.config.button_gpio_next_pin,
                ButtonId.BACK: self.config.button_gpio_back_pin,
                ButtonId.CONFIRM: self.config.button_gpio_confirm_pin,
                ButtonId.SPECIAL: self.config.button_gpio_special_pin,
            },
            debounce_ms=self.config.button_gpio_debounce_ms,
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
        self._display_update_loop = asyncio.get_running_loop()
        await self.plugin_service.rescan()
        self.theme_service.rescan()

        themes = self.theme_service.list_themes()
        state = self.state_repository.load_or_create(self.settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        state = self._sanitize_state_configuration(state)
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

        if state.hardware_profile != "dummy":
            try:
                await self.plugin_service.activate_hardware_profile(state.hardware_profile)
                state = self.state_repository.load_or_create(
                    self.settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi"
                )
            except ValueError:
                logger.warning(
                    "Stored hardware profile could not be activated during startup.",
                    extra={"hardware_profile": state.hardware_profile},
                )

        self.refresh_display_driver(profile_id=state.hardware_profile)
        self.render_service.set_theme(state.active_theme_id)
        self._render_current_pet_frame()
        self.gpio_button_driver.start()

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
        self.gpio_button_driver.stop()
        self._display_update_loop = None

    def refresh_display_driver(self, profile_id: str) -> dict[str, Any]:
        normalized = _normalize_hardware_profile_id(profile_id, default="dummy")

        if normalized == "dummy":
            self._switch_display_driver(self._create_dummy_driver())
            self._render_current_pet_frame()
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
                self._render_hardware_test_pattern(backend_label=normalized)
                self._render_current_pet_frame()
                status = self._record_hardware_status(
                    ok=True,
                    backend=normalized,
                    message="Hardware backend initialized successfully.",
                )
                return status
            except Exception as exc:
                logger.exception("Plugin display driver failed to initialize.", extra={"profile_id": normalized})
                self._switch_display_driver(self._create_dummy_driver())
                self._render_current_pet_frame()
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
        self._render_current_pet_frame()
        status = self._record_hardware_status(
            ok=False,
            backend=normalized,
            message="Requested hardware backend is unavailable. Dummy display is active.",
        )
        return status

    def get_hardware_status(self) -> dict[str, Any]:
        return dict(self._hardware_status)

    def get_display_capabilities(self) -> dict[str, Any]:
        return {
            "width": self.active_display_capabilities.width,
            "height": self.active_display_capabilities.height,
            "mode": self.active_display_capabilities.color_mode,
        }

    def get_display_frame_png(self) -> bytes:
        return self.framebuffer.to_png_bytes()

    def get_display_frame_meta(self) -> dict[str, Any]:
        return {
            "version": self.framebuffer.version,
            "updated_at_ms": self.framebuffer.updated_at_ms,
            "width": self.active_display_capabilities.width,
            "height": self.active_display_capabilities.height,
        }

    def publish_button_event(self, button: ButtonId, ts_ms: int | None = None) -> None:
        self.input_router.publish(
            InputEvent(
                button=button,
                ts_ms=ts_ms if ts_ms is not None else int(time.time() * 1000),
            )
        )

    async def wait_for_display_update(self, last_seen_version: int, timeout_seconds: float = 10.0) -> dict[str, Any] | None:
        async with self._display_update_condition:
            if self._latest_display_version > last_seen_version:
                return self.get_display_frame_meta()
            try:
                await asyncio.wait_for(
                    self._display_update_condition.wait_for(lambda: self._latest_display_version > last_seen_version),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return None
        return self.get_display_frame_meta()

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
            try:
                driver.sleep()
            except Exception:
                logger.debug("Failed to cleanup candidate display driver after init error.", exc_info=True)
            raise
        new_capabilities = self._safe_get_capabilities(driver)

        try:
            self.display_driver.sleep()
        except Exception:
            logger.debug("Current display driver did not sleep cleanly.", exc_info=True)

        self.display_driver = driver
        self.display_manager.set_sinks([DisplayDriverSink(driver)])
        self._apply_display_capabilities(new_capabilities)

    def _safe_get_capabilities(self, driver: DisplayDriver) -> DisplayCapabilities:
        try:
            capabilities = driver.get_capabilities()
            if capabilities.width <= 0 or capabilities.height <= 0:
                return self.DEFAULT_CAPABILITIES
            return capabilities
        except Exception:
            logger.exception("Unable to read display capabilities. Falling back to defaults.")
            return self.DEFAULT_CAPABILITIES

    def _apply_display_capabilities(self, capabilities: DisplayCapabilities) -> None:
        self.active_display_capabilities = capabilities

        if self.framebuffer.width == capabilities.width and self.framebuffer.height == capabilities.height:
            self.render_service.set_display_context(self.framebuffer, capabilities)
            return

        self.framebuffer = FrameBuffer1Bit(width=capabilities.width, height=capabilities.height)
        self._latest_display_version = self.framebuffer.version
        self._latest_display_updated_at_ms = self.framebuffer.updated_at_ms
        self.render_service.set_display_context(self.framebuffer, capabilities)

    def _render_hardware_test_pattern(self, backend_label: str) -> None:
        frame_a = Image.new("1", (self.framebuffer.width, self.framebuffer.height), color=1)
        draw_a = ImageDraw.Draw(frame_a)
        draw_a.rectangle((0, 0, self.framebuffer.width - 1, self.framebuffer.height - 1), outline=0, width=2)
        draw_a.text((12, 12), "Clawgotchi ready", fill=0)
        draw_a.text((12, 36), backend_label, fill=0)
        draw_a.text((12, 60), "SPI online", fill=0)

        frame_b = Image.new("1", (self.framebuffer.width, self.framebuffer.height), color=1)
        draw_b = ImageDraw.Draw(frame_b)
        draw_b.rectangle((0, 0, self.framebuffer.width - 1, self.framebuffer.height - 1), outline=0, width=2)
        draw_b.text((12, 12), "Clawgotchi ready", fill=0)
        draw_b.text((12, 36), "Display test frame 2/2", fill=0)

        self.render_service.push_image(frame_a)
        self.render_service.push_image(frame_b)

    def _record_hardware_status(self, ok: bool, backend: str, message: str) -> dict[str, Any]:
        status = {
            "ok": ok,
            "backend": backend,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._hardware_status = status
        return status

    def _menu_indicators(self) -> list[str]:
        return [
            f"HW:{self._hardware_status.get('backend', 'dummy')[:6]}",
            f"W:{self.active_display_capabilities.width}",
        ]

    def _on_display_push(self, version: int, updated_at_ms: int) -> None:
        self._latest_display_version = version
        self._latest_display_updated_at_ms = updated_at_ms

        if self._display_update_loop is None or self._display_update_loop.is_closed():
            return

        self._display_update_loop.call_soon_threadsafe(self._schedule_display_update_notification)

    def _schedule_display_update_notification(self) -> None:
        asyncio.create_task(self._notify_display_update())

    async def _notify_display_update(self) -> None:
        async with self._display_update_condition:
            self._display_update_condition.notify_all()

    def _sanitize_state_configuration(self, state: Any) -> Any:
        changed = False

        known_plugin_ids = {plugin["plugin_id"] for plugin in self.plugin_repository.list_plugins()}
        sanitized_enabled_plugins = sorted(
            plugin_id
            for plugin_id in dict.fromkeys(state.enabled_plugin_ids)
            if plugin_id in known_plugin_ids
        )
        if sanitized_enabled_plugins != state.enabled_plugin_ids:
            state.enabled_plugin_ids = sanitized_enabled_plugins
            changed = True

        normalized_profile = _normalize_hardware_profile_id(state.hardware_profile, default="dummy")
        known_profile_ids = {profile["id"] for profile in self.plugin_service.list_hardware_profiles()}
        if normalized_profile not in known_profile_ids:
            normalized_profile = "dummy"

        if normalized_profile != state.hardware_profile:
            state.hardware_profile = normalized_profile
            changed = True

        if not changed:
            return state

        self.state_repository.save_state(
            state=state,
            source="state_configuration_sanitized",
            command_id=None,
            events=[],
        )
        self.settings_repository.set("setup.hardware_profile", state.hardware_profile)
        return state

    def _render_current_pet_frame(self) -> None:
        try:
            pet_name = self.settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi"
            state = self.state_repository.load_or_create(pet_name)
            now_ts = time.time()
            pet_state = PetState.from_dict(
                state.pet_state.to_dict(),
                fallback_name=state.pet.name,
                fallback_emotion=state.pet.emotion.value,
            )
            pet_state.ensure_idle_if_expired(now_ts)
            self.render_service.set_theme(state.active_theme_id)
            self.render_service.render_frame(pet_state, now_ts=now_ts)
            self.render_service.push_framebuffer()
        except Exception:
            logger.exception("Failed to render current pet frame after display backend change.")
