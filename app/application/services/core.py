from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any

from app.application.command_processing import CommandQueueProtocol
from app.application.interfaces import (
    PluginContext,
    PluginLoaderProtocol,
    PluginRepositoryProtocol,
    SettingsRepositoryProtocol,
    StateRepositoryProtocol,
    ThemeLoaderProtocol,
    ThemeRepositoryProtocol,
)
from app.application.services.render_service import RenderService
from app.domain.entities import DeviceState
from app.domain.events import DomainEvent
from app.domain.snapshots import StateSnapshot
from app.domain.value_objects import PetCommand, utc_now

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    accepted: bool
    command_id: str
    state_version: int


@dataclass(slots=True)
class SetupRequest:
    pet_name: str
    theme_id: str
    plugin_ids: list[str]
    hardware_profile: str


class PluginRuntime:
    def __init__(
        self,
        plugin_loader: PluginLoaderProtocol,
        settings_repository: SettingsRepositoryProtocol,
    ) -> None:
        self._plugin_loader = plugin_loader
        self._settings_repository = settings_repository
        self._manifests_by_id: dict[str, Any] = {}
        self._instances_by_id: dict[str, Any] = {}

    def set_manifests(self, manifests: list[Any]) -> None:
        self._manifests_by_id = {manifest.plugin_id: manifest for manifest in manifests}

    async def synchronize_enabled(self, enabled_ids: list[str]) -> None:
        enabled_set = set(enabled_ids)
        for plugin_id in list(self._instances_by_id.keys()):
            if plugin_id not in enabled_set:
                plugin = self._instances_by_id.pop(plugin_id)
                await plugin.on_shutdown()

        context = PluginContext(settings=self._settings_repository.get_prefix("plugin."))
        for plugin_id in enabled_ids:
            try:
                await self.activate(plugin_id, context)
            except Exception:
                logger.exception("Enabled plugin failed to start.", extra={"plugin_id": plugin_id})

    async def activate(self, plugin_id: str, context: PluginContext | None = None) -> None:
        if plugin_id in self._instances_by_id:
            return
        manifest = self._manifests_by_id.get(plugin_id)
        if manifest is None:
            raise ValueError(f"Plugin '{plugin_id}' is not available.")
        instance = self._plugin_loader.load_plugin(manifest)
        ctx = context or PluginContext(settings=self._settings_repository.get_prefix("plugin."))
        await instance.on_startup(ctx)
        self._instances_by_id[plugin_id] = instance

    async def deactivate(self, plugin_id: str) -> None:
        plugin = self._instances_by_id.pop(plugin_id, None)
        if plugin is not None:
            await plugin.on_shutdown()

    async def on_tick(self, state: DeviceState) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for plugin in self._instances_by_id.values():
            events.extend(await plugin.on_tick(state))
        return events

    async def on_command(self, state: DeviceState, command: PetCommand) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for plugin in self._instances_by_id.values():
            events.extend(await plugin.on_command(state, command))
        return events

    async def shutdown(self) -> None:
        for plugin_id in list(self._instances_by_id.keys()):
            await self.deactivate(plugin_id)


class SendCommandService:
    def __init__(self, queue: CommandQueueProtocol, timeout_seconds: float = 3.0) -> None:
        self._queue = queue
        self._timeout_seconds = timeout_seconds

    async def send(self, command: PetCommand) -> CommandResult:
        result_future = await self._queue.enqueue(command)
        state_version = await asyncio.wait_for(result_future, timeout=self._timeout_seconds)
        return CommandResult(accepted=True, command_id=command.command_id, state_version=state_version)


class CommandHandlerService:
    def __init__(
        self,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
        plugin_runtime: PluginRuntime,
        render_service: RenderService,
        lock: asyncio.Lock,
    ) -> None:
        self._state_repository = state_repository
        self._settings_repository = settings_repository
        self._plugin_runtime = plugin_runtime
        self._render_service = render_service
        self._lock = lock

    async def handle(self, command: PetCommand) -> int:
        async with self._lock:
            default_pet_name = self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi"
            state = self._state_repository.load_or_create(default_pet_name)

            now_ts = time.time()
            events = state.apply_command(command)
            events.extend(await self._plugin_runtime.on_command(state, command))
            state.pet_state.sync_identity(name=state.pet.name, emotion=state.pet.emotion.value)

            force_render = False
            if command.type == "scratch":
                self._render_service.set_theme(state.active_theme_id)
                scratch_duration_ms = self._render_service.get_animation_duration_ms("scratch")
                if scratch_duration_ms <= 0:
                    scratch_duration_ms = RenderService.SCRATCH_DEFAULT_DURATION_MS
                state.pet_state.emotion = "happy"
                state.pet_state.set_temporary_animation("scratch", scratch_duration_ms, now_ts=now_ts)
                force_render = True
            else:
                state.pet_state.ensure_idle_if_expired(now_ts)

            rendered = self._render_if_needed(state=state, now_ts=now_ts, force=force_render)
            if rendered:
                events.append(
                    DomainEvent(
                        event_type="frame_rendered",
                        payload={
                            "animation": state.pet_state.current_animation,
                            "source": "command",
                        },
                    )
                )

            state_version = self._state_repository.save_state(
                state=state,
                source=f"command:{command.type}",
                command_id=command.command_id,
                events=events,
            )
            return state_version

    def _render_if_needed(self, state: DeviceState, now_ts: float, force: bool = False) -> bool:
        self._render_service.set_theme(state.active_theme_id)
        try:
            if not force:
                decision = self._render_service.should_render(state.pet_state, now_ts=now_ts)
                if not decision.should_render:
                    return False

            image = self._render_service.render_frame(state.pet_state, now_ts=now_ts)
            self._render_service.push_frame(image)
            return True
        except Exception:
            logger.exception("Command render step failed.")
            return False


class TickLoopService:
    def __init__(
        self,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
        plugin_runtime: PluginRuntime,
        render_service: RenderService,
        lock: asyncio.Lock,
    ) -> None:
        self._state_repository = state_repository
        self._settings_repository = settings_repository
        self._plugin_runtime = plugin_runtime
        self._render_service = render_service
        self._lock = lock

    async def run_tick(self) -> int:
        async with self._lock:
            default_pet_name = self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi"
            state = self._state_repository.load_or_create(default_pet_name)

            now_ts = time.time()
            events = state.apply_tick()
            events.extend(await self._plugin_runtime.on_tick(state))

            state.pet_state.sync_identity(name=state.pet.name, emotion=state.pet.emotion.value)
            state.pet_state.ensure_idle_if_expired(now_ts)

            rendered = self._render_if_needed(state=state, now_ts=now_ts)
            if rendered:
                events.append(
                    DomainEvent(
                        event_type="frame_rendered",
                        payload={
                            "animation": state.pet_state.current_animation,
                            "source": "tick",
                        },
                    )
                )

            state_version = self._state_repository.save_state(
                state=state,
                source="tick",
                command_id=None,
                events=events,
            )
            return state_version

    def _render_if_needed(self, state: DeviceState, now_ts: float) -> bool:
        self._render_service.set_theme(state.active_theme_id)
        try:
            decision = self._render_service.should_render(state.pet_state, now_ts=now_ts)
            if not decision.should_render:
                return False

            image = self._render_service.render_frame(state.pet_state, now_ts=now_ts)
            self._render_service.push_frame(image)
            return True
        except Exception:
            logger.exception("Tick render step failed.")
            return False


class InitializeDeviceService:
    def __init__(
        self,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
        plugin_repository: PluginRepositoryProtocol,
        theme_repository: ThemeRepositoryProtocol,
        plugin_runtime: PluginRuntime,
    ) -> None:
        self._state_repository = state_repository
        self._settings_repository = settings_repository
        self._plugin_repository = plugin_repository
        self._theme_repository = theme_repository
        self._plugin_runtime = plugin_runtime

    async def initialize(self, request: SetupRequest) -> int:
        state = self._state_repository.load_or_create(request.pet_name)
        state.pet.name = request.pet_name.strip() or state.pet.name
        state.pet_state.name = state.pet.name
        state.hardware_profile = request.hardware_profile.strip() or "dummy"

        available_themes = {item["theme_id"] for item in self._theme_repository.list_themes()}
        if request.theme_id in available_themes:
            state.active_theme_id = request.theme_id
            self._theme_repository.activate(request.theme_id)

        available_plugins = {item["plugin_id"] for item in self._plugin_repository.list_plugins()}
        selected_plugins = [plugin_id for plugin_id in request.plugin_ids if plugin_id in available_plugins]

        for plugin in available_plugins:
            self._plugin_repository.set_enabled(plugin, plugin in selected_plugins)

        state.enabled_plugin_ids = sorted(selected_plugins)
        version = self._state_repository.save_state(
            state=state,
            source="setup",
            command_id=None,
            events=[
                DomainEvent(
                    event_type="device_initialized",
                    payload={
                        "pet_name": state.pet.name,
                        "theme_id": state.active_theme_id,
                        "plugin_ids": state.enabled_plugin_ids,
                        "hardware_profile": state.hardware_profile,
                    },
                )
            ],
        )

        self._settings_repository.set("setup.completed", "true")
        self._settings_repository.set("setup.pet_name", state.pet.name)
        self._settings_repository.set("setup.hardware_profile", state.hardware_profile)

        await self._plugin_runtime.synchronize_enabled(state.enabled_plugin_ids)
        return version

    def is_completed(self) -> bool:
        return (self._settings_repository.get("setup.completed", "false") or "false").lower() == "true"


class PluginService:
    def __init__(
        self,
        plugin_loader: PluginLoaderProtocol,
        plugin_repository: PluginRepositoryProtocol,
        state_repository: StateRepositoryProtocol,
        plugin_runtime: PluginRuntime,
        settings_repository: SettingsRepositoryProtocol,
    ) -> None:
        self._plugin_loader = plugin_loader
        self._plugin_repository = plugin_repository
        self._state_repository = state_repository
        self._plugin_runtime = plugin_runtime
        self._settings_repository = settings_repository

    async def rescan(self) -> list[dict[str, Any]]:
        manifests = self._plugin_loader.scan()
        self._plugin_repository.upsert_manifests(manifests)
        self._plugin_runtime.set_manifests(manifests)
        await self._plugin_runtime.synchronize_enabled(self._plugin_repository.list_enabled_ids())
        return self._plugin_repository.list_plugins()

    async def install_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugins = await self.rescan()
        if plugin_id not in {plugin["plugin_id"] for plugin in plugins}:
            raise ValueError(f"Plugin '{plugin_id}' was not found in filesystem plugins.")
        return await self.enable(plugin_id)

    async def enable(self, plugin_id: str) -> dict[str, Any]:
        self._plugin_repository.set_enabled(plugin_id, True)
        await self._plugin_runtime.activate(plugin_id)

        state = self._state_repository.load_or_create(self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        enabled = set(state.enabled_plugin_ids)
        enabled.add(plugin_id)
        state.enabled_plugin_ids = sorted(enabled)
        self._state_repository.save_state(
            state=state,
            source="plugin_enabled",
            command_id=None,
            events=[DomainEvent(event_type="plugin_enabled", payload={"plugin_id": plugin_id})],
        )
        return self._find_plugin(plugin_id)

    async def disable(self, plugin_id: str) -> dict[str, Any]:
        self._plugin_repository.set_enabled(plugin_id, False)
        await self._plugin_runtime.deactivate(plugin_id)

        state = self._state_repository.load_or_create(self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        state.enabled_plugin_ids = [value for value in state.enabled_plugin_ids if value != plugin_id]
        self._state_repository.save_state(
            state=state,
            source="plugin_disabled",
            command_id=None,
            events=[DomainEvent(event_type="plugin_disabled", payload={"plugin_id": plugin_id})],
        )
        return self._find_plugin(plugin_id)

    def list_plugins(self) -> list[dict[str, Any]]:
        return self._plugin_repository.list_plugins()

    def _find_plugin(self, plugin_id: str) -> dict[str, Any]:
        for plugin in self._plugin_repository.list_plugins():
            if plugin["plugin_id"] == plugin_id:
                return plugin
        raise ValueError(f"Plugin '{plugin_id}' was not found.")


class ThemeService:
    def __init__(
        self,
        theme_loader: ThemeLoaderProtocol,
        theme_repository: ThemeRepositoryProtocol,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
    ) -> None:
        self._theme_loader = theme_loader
        self._theme_repository = theme_repository
        self._state_repository = state_repository
        self._settings_repository = settings_repository

    def rescan(self) -> list[dict[str, Any]]:
        manifests = self._theme_loader.scan()
        self._theme_repository.upsert_manifests(manifests)
        return self._theme_repository.list_themes()

    def activate_theme(self, theme_id: str) -> dict[str, Any]:
        available = {theme["theme_id"] for theme in self._theme_repository.list_themes()}
        if theme_id not in available:
            raise ValueError(f"Theme '{theme_id}' was not found.")

        self._theme_repository.activate(theme_id)
        state = self._state_repository.load_or_create(self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        state.active_theme_id = theme_id
        self._state_repository.save_state(
            state=state,
            source="theme_activated",
            command_id=None,
            events=[DomainEvent(event_type="theme_activated", payload={"theme_id": theme_id})],
        )
        return self._find_theme(theme_id)

    def list_themes(self) -> list[dict[str, Any]]:
        return self._theme_repository.list_themes()

    def _find_theme(self, theme_id: str) -> dict[str, Any]:
        for theme in self._theme_repository.list_themes():
            if theme["theme_id"] == theme_id:
                return theme
        raise ValueError(f"Theme '{theme_id}' was not found.")


class StateTransferService:
    SUPPORTED_SCHEMA_VERSION = 1

    def __init__(
        self,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
        plugin_repository: PluginRepositoryProtocol,
        theme_repository: ThemeRepositoryProtocol,
        plugin_runtime: PluginRuntime,
    ) -> None:
        self._state_repository = state_repository
        self._settings_repository = settings_repository
        self._plugin_repository = plugin_repository
        self._theme_repository = theme_repository
        self._plugin_runtime = plugin_runtime

    async def export_state(self) -> dict[str, Any]:
        state = self._state_repository.load_or_create(self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi")
        snapshot = StateSnapshot(
            schema_version=state.schema_version,
            state_version=state.state_version,
            state=state.to_dict(),
        )
        return snapshot.to_dict()

    async def import_state(self, payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        snapshot = StateSnapshot.from_dict(payload)
        if snapshot.schema_version != self.SUPPORTED_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema version {snapshot.schema_version}. "
                f"Supported schema version is {self.SUPPORTED_SCHEMA_VERSION}."
            )

        restored_state = DeviceState.from_dict(snapshot.state)

        if dry_run:
            return {
                "dry_run": True,
                "valid": True,
                "schema_version": snapshot.schema_version,
                "state_version": snapshot.state_version,
                "pet_name": restored_state.pet.name,
            }

        state_version = self._state_repository.restore_state(restored_state, source="import")

        known_plugins = {plugin["plugin_id"] for plugin in self._plugin_repository.list_plugins()}
        selected_plugins = [plugin_id for plugin_id in restored_state.enabled_plugin_ids if plugin_id in known_plugins]
        for plugin_id in known_plugins:
            self._plugin_repository.set_enabled(plugin_id, plugin_id in selected_plugins)

        await self._plugin_runtime.synchronize_enabled(selected_plugins)

        known_themes = {theme["theme_id"] for theme in self._theme_repository.list_themes()}
        if restored_state.active_theme_id in known_themes:
            self._theme_repository.activate(restored_state.active_theme_id)

        self._settings_repository.set("setup.pet_name", restored_state.pet.name)
        self._settings_repository.set("setup.hardware_profile", restored_state.hardware_profile)

        return {
            "dry_run": False,
            "imported": True,
            "state_version": state_version,
            "schema_version": restored_state.schema_version,
            "imported_at": utc_now().isoformat(),
        }


class StatusService:
    def __init__(
        self,
        state_repository: StateRepositoryProtocol,
        settings_repository: SettingsRepositoryProtocol,
        initialize_device_service: InitializeDeviceService,
    ) -> None:
        self._state_repository = state_repository
        self._settings_repository = settings_repository
        self._initialize_device_service = initialize_device_service

    def get_status(self) -> dict[str, Any]:
        pet_name = self._settings_repository.get("setup.pet_name", "Clawgotchi") or "Clawgotchi"
        state = self._state_repository.load_or_create(pet_name)
        return {
            "setup_completed": self._initialize_device_service.is_completed(),
            "state": state.to_dict(),
            "state_version": state.state_version,
        }
