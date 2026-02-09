from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(slots=True)
class RuntimeConfig:
    app_name: str
    host: str
    port: int
    log_level: str
    tick_interval_seconds: float
    database_url: str
    plugin_directory: Path
    theme_directory: Path
    config_file: Path
    api_key: str
    display_type: str
    display_vendor: str
    display_rotation: int
    display_use_partial: bool
    display_dithering: bool
    display_debug_write_png: bool
    display_debug_png_path: str


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAW_", env_file=".env", extra="ignore")

    app_name: str = "Clawgotchi"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    tick_interval_seconds: float = 2.0
    database_url: str = "sqlite:///./clawgotchi.db"
    plugin_directory: str = "./plugins"
    theme_directory: str = "./themes"
    config_file: str = "./config/defaults.toml"
    api_key: str = ""
    display_type: str = "dummy"
    display_vendor: str = "waveshare"
    display_rotation: int = 0
    display_use_partial: bool = False
    display_dithering: bool = False
    display_debug_write_png: bool = True
    display_debug_png_path: str = "/tmp/clawgotchi_last_frame.png"


class ConfigResolver:
    def __init__(self, extra_overrides: dict[str, Any] | None = None) -> None:
        self._env = EnvironmentSettings()
        self._extra_overrides = extra_overrides or {}

    def resolve(self, db_overrides: dict[str, str] | None = None) -> RuntimeConfig:
        defaults = {
            "app_name": "Clawgotchi",
            "host": "0.0.0.0",
            "port": 8000,
            "log_level": "INFO",
            "tick_interval_seconds": 2.0,
            "database_url": "sqlite:///./clawgotchi.db",
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
            "config_file": "./config/defaults.toml",
            "api_key": "",
            "display_type": "dummy",
            "display_vendor": "waveshare",
            "display_rotation": 0,
            "display_use_partial": False,
            "display_dithering": False,
            "display_debug_write_png": True,
            "display_debug_png_path": "/tmp/clawgotchi_last_frame.png",
        }

        env_values = self._env.model_dump()
        config_file_path = Path(str(env_values.get("config_file", defaults["config_file"]))).expanduser()
        file_values = self._load_file_values(config_file_path)

        merged: dict[str, Any] = {}
        merged.update(defaults)
        merged.update(file_values)
        merged.update(env_values)

        if db_overrides:
            merged.update(self._normalize_types(db_overrides))

        merged.update(self._extra_overrides)

        plugin_directory = Path(str(merged["plugin_directory"])).expanduser()
        theme_directory = Path(str(merged["theme_directory"])).expanduser()
        final_config_file = Path(str(merged["config_file"])).expanduser()

        return RuntimeConfig(
            app_name=str(merged["app_name"]),
            host=str(merged["host"]),
            port=int(merged["port"]),
            log_level=str(merged["log_level"]),
            tick_interval_seconds=float(merged["tick_interval_seconds"]),
            database_url=str(merged["database_url"]),
            plugin_directory=plugin_directory,
            theme_directory=theme_directory,
            config_file=final_config_file,
            api_key=str(merged.get("api_key", "")),
            display_type=str(merged["display_type"]),
            display_vendor=str(merged["display_vendor"]),
            display_rotation=int(merged["display_rotation"]),
            display_use_partial=self._coerce_bool(merged["display_use_partial"]),
            display_dithering=self._coerce_bool(merged["display_dithering"]),
            display_debug_write_png=self._coerce_bool(merged["display_debug_write_png"]),
            display_debug_png_path=str(merged["display_debug_png_path"]),
        )

    def _load_file_values(self, config_file: Path) -> dict[str, Any]:
        if not config_file.exists():
            return {}
        with config_file.open("rb") as handle:
            payload = tomllib.load(handle)
        return {key: value for key, value in payload.items() if not isinstance(value, dict)}

    def _normalize_types(self, raw_values: dict[str, str]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, raw_value in raw_values.items():
            if key in {"port", "display_rotation"}:
                normalized[key] = int(raw_value)
            elif key in {"tick_interval_seconds"}:
                normalized[key] = float(raw_value)
            elif key in {"display_use_partial", "display_dithering", "display_debug_write_png"}:
                normalized[key] = self._to_bool(raw_value)
            else:
                normalized[key] = raw_value
        return normalized

    def _to_bool(self, value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return self._to_bool(value)
        return bool(value)
