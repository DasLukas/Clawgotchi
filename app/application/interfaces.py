from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.entities import DeviceState
from app.domain.events import DomainEvent
from app.domain.value_objects import PetCommand


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    entrypoint: str
    class_name: str
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "class_name": self.class_name,
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ThemeManifest:
    theme_id: str
    name: str
    version: str
    description: str
    preview: str
    stylesheet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme_id": self.theme_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "preview": self.preview,
            "stylesheet": self.stylesheet,
        }


@dataclass(slots=True)
class PluginContext:
    settings: dict[str, str]


class PluginBase(ABC):
    plugin_id: str = "base"
    name: str = "Base Plugin"

    async def on_startup(self, context: PluginContext) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    async def on_tick(self, state: DeviceState) -> list[DomainEvent]:
        return []

    async def on_command(self, state: DeviceState, command: PetCommand) -> list[DomainEvent]:
        return []

    def get_commands(self) -> list[str]:
        return []

    def get_emotions(self) -> list[str]:
        return []

    def get_mini_games(self) -> list[str]:
        return []

    def get_hardware_drivers(self) -> list[str]:
        return []

    def create_display_driver(self, profile_id: str, settings: Any) -> Any | None:
        return None

    def get_ui_extensions(self) -> list[str]:
        return []


class SettingsRepositoryProtocol(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None:
        ...

    def set(self, key: str, value: str) -> None:
        ...

    def get_prefix(self, prefix: str) -> dict[str, str]:
        ...


class StateRepositoryProtocol(Protocol):
    def load_state(self) -> DeviceState | None:
        ...

    def load_or_create(self, pet_name: str) -> DeviceState:
        ...

    def save_state(
        self,
        state: DeviceState,
        source: str,
        command_id: str | None,
        events: list[DomainEvent],
    ) -> int:
        ...

    def restore_state(self, state: DeviceState, source: str) -> int:
        ...

    def get_state_version(self) -> int:
        ...


class PluginRepositoryProtocol(Protocol):
    def upsert_manifests(self, manifests: list[PluginManifest]) -> None:
        ...

    def list_plugins(self) -> list[dict[str, Any]]:
        ...

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        ...

    def list_enabled_ids(self) -> list[str]:
        ...


class ThemeRepositoryProtocol(Protocol):
    def upsert_manifests(self, manifests: list[ThemeManifest]) -> None:
        ...

    def list_themes(self) -> list[dict[str, Any]]:
        ...

    def activate(self, theme_id: str) -> None:
        ...

    def get_active_id(self) -> str | None:
        ...


class PluginLoaderProtocol(Protocol):
    def scan(self) -> list[PluginManifest]:
        ...

    def load_plugin(self, manifest: PluginManifest) -> PluginBase:
        ...


class ThemeLoaderProtocol(Protocol):
    def scan(self) -> list[ThemeManifest]:
        ...
