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


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAW_", env_file=".env", extra="ignore")

    app_name: str = "Clawgotchi"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    tick_interval_seconds: float = 5.0
    database_url: str = "sqlite:///./clawgotchi.db"
    plugin_directory: str = "./plugins"
    theme_directory: str = "./themes"
    config_file: str = "./config/defaults.toml"
    api_key: str = ""


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
            "tick_interval_seconds": 5.0,
            "database_url": "sqlite:///./clawgotchi.db",
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
            "config_file": "./config/defaults.toml",
            "api_key": "",
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
            if key in {"port"}:
                normalized[key] = int(raw_value)
            elif key in {"tick_interval_seconds"}:
                normalized[key] = float(raw_value)
            else:
                normalized[key] = raw_value
        return normalized
