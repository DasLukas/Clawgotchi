from __future__ import annotations

import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(slots=True)
class RuntimeConfig:
    """Resolved runtime configuration after applying all supported sources.

    Attributes:
        app_name: Human-readable application name shown in UI.
        host: Bind host for the HTTP server.
        port: Bind port for the HTTP server.
        log_level: Root logging level.
        tick_interval_seconds: Tick loop cadence in seconds.
        database_url: SQLAlchemy database URL.
        runtime_home: Writable runtime base directory.
        logs_directory: Runtime log directory.
        cache_directory: Runtime cache directory.
        config_directory: Runtime config override directory.
        plugin_directory: Primary writable plugin directory (runtime).
        theme_directory: Primary writable theme directory (runtime).
        plugin_directories: Ordered plugin discovery roots (runtime first).
        theme_directories: Ordered theme discovery roots (runtime first).
        built_in_plugin_directory: Read-only built-in plugin directory in repo.
        built_in_theme_directory: Read-only built-in theme directory in repo.
        runtime_env_file: Runtime environment file path.
        config_file: Global defaults TOML path.
        api_key: Optional API key used for `/api/v1` endpoints.
        display_type: Display backend name.
        display_rotation: Rotation in degrees (0/90/180/270).
        display_use_partial: Partial refresh usage for supported drivers.
        display_dithering: Dithering toggle for render output.
        display_debug_write_png: Enable PNG debug dump for dummy backend.
        display_debug_png_path: Debug image output path.
    """

    app_name: str
    host: str
    port: int
    log_level: str
    tick_interval_seconds: float
    database_url: str
    runtime_home: Path
    logs_directory: Path
    cache_directory: Path
    config_directory: Path
    plugin_directory: Path
    theme_directory: Path
    plugin_directories: tuple[Path, ...]
    theme_directories: tuple[Path, ...]
    built_in_plugin_directory: Path
    built_in_theme_directory: Path
    runtime_env_file: Path
    config_file: Path
    api_key: str
    display_type: str
    display_rotation: int
    display_use_partial: bool
    display_dithering: bool
    display_debug_write_png: bool
    display_debug_png_path: str


class EnvironmentSettings(BaseSettings):
    """Environment-backed settings model.

    Values are loaded from process environment and an optional env-file. The
    env-file location is supplied by `ConfigResolver` at runtime.
    """

    model_config = SettingsConfigDict(env_prefix="CLAW_", env_file=None, extra="ignore")

    app_name: str = "Clawgotchi"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    runtime_home: str | None = None
    database_url: str | None = None
    plugin_directory: str | None = None
    theme_directory: str | None = None
    plugin_directories: str | None = None
    theme_directories: str | None = None
    config_file: str | None = None
    env_file: str | None = None
    tick_interval_seconds: float = 2.0
    api_key: str = ""
    display_type: str = "dummy"
    display_rotation: int = 0
    display_use_partial: bool = False
    display_dithering: bool = False
    display_debug_write_png: bool = True
    display_debug_png_path: str = "/tmp/clawgotchi_last_frame.png"


def get_repo_root() -> Path:
    """Return the repository root directory for the current checkout."""

    return Path(__file__).resolve().parent.parent


def get_runtime_home() -> Path:
    """Resolve the default per-user runtime home path for the current OS.

    Resolution order:
    1. `CLAW_RUNTIME_HOME` environment override
    2. Platform default user-data directory
    """

    explicit_home = os.environ.get("CLAW_RUNTIME_HOME")
    if explicit_home:
        return Path(explicit_home).expanduser()

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser() / "Clawgotchi"
        return Path.home() / "AppData" / "Local" / "Clawgotchi"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Clawgotchi"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base_directory = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return base_directory / "clawgotchi"


def get_runtime_layout(runtime_home: Path | None = None) -> dict[str, Path]:
    """Build the canonical runtime directory/file layout.

    Parameters:
        runtime_home: Optional runtime base directory override.

    Returns:
        Mapping with canonical runtime directories and important file paths.
    """

    home = (runtime_home or get_runtime_home()).expanduser()
    return {
        "runtime_home": home,
        "db_directory": home / "db",
        "database_path": home / "db" / "clawgotchi.db",
        "logs_directory": home / "logs",
        "plugin_directory": home / "plugins",
        "theme_directory": home / "themes",
        "cache_directory": home / "cache",
        "config_directory": home / "config",
        "bin_directory": home / "bin",
        "runtime_env_file": home / ".env",
        "plugin_registry_file": home / "plugins" / "registry.json",
    }


def ensure_runtime_layout(runtime_home: Path | None = None) -> dict[str, Path]:
    """Create runtime directories with user-scoped permissions.

    Parameters:
        runtime_home: Optional runtime base directory override.

    Returns:
        The same layout mapping as `get_runtime_layout`.
    """

    layout = get_runtime_layout(runtime_home)
    for key in {
        "runtime_home",
        "db_directory",
        "logs_directory",
        "plugin_directory",
        "theme_directory",
        "cache_directory",
        "config_directory",
        "bin_directory",
    }:
        path = layout[key]
        path.mkdir(parents=True, exist_ok=True)
        _set_posix_permissions(path, mode=0o700)
    return layout


def assert_runtime_home_writable(runtime_home: Path) -> None:
    """Validate that runtime home can be written by the current user.

    Parameters:
        runtime_home: Runtime base directory to validate.

    Raises:
        PermissionError: If runtime home is not writable.
    """

    ensure_runtime_layout(runtime_home)
    try:
        with tempfile.NamedTemporaryFile(prefix=".write-test-", dir=str(runtime_home), delete=True):
            pass
    except OSError as exc:
        raise PermissionError(
            "Runtime home is not writable. "
            f"Please adjust CLAW_RUNTIME_HOME or directory permissions: {runtime_home}"
        ) from exc


def _set_posix_permissions(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        return


def _resolve_env_file() -> Path | None:
    explicit = os.environ.get("CLAW_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser()

    runtime_home = os.environ.get("CLAW_RUNTIME_HOME")
    if runtime_home:
        runtime_candidate = Path(runtime_home).expanduser() / ".env"
        if runtime_candidate.exists():
            return runtime_candidate

    repo_candidate = get_repo_root() / ".env"
    if repo_candidate.exists():
        return repo_candidate

    local_candidate = Path(".env")
    if local_candidate.exists():
        return local_candidate

    return None


def _sqlite_url_for_path(database_path: Path) -> str:
    resolved = database_path.expanduser().resolve()
    if os.name == "nt":
        return f"sqlite:///{resolved.as_posix()}"
    return f"sqlite:///{resolved.as_posix()}"


def _is_windows_absolute_path(path_value: str) -> bool:
    return re.match(r"^[A-Za-z]:[/\\]", path_value) is not None


def _normalize_sqlite_database_url(database_url: str, runtime_home: Path) -> str:
    normalized_url = database_url.strip()
    if not normalized_url:
        return _sqlite_url_for_path(get_runtime_layout(runtime_home)["database_path"])
    if normalized_url == "sqlite:///:memory:":
        return normalized_url
    if not normalized_url.startswith("sqlite:///"):
        return normalized_url

    path_component = normalized_url.removeprefix("sqlite:///")
    if path_component.startswith("/") or _is_windows_absolute_path(path_component):
        return normalized_url

    resolved_path = (runtime_home / path_component).expanduser().resolve()
    return _sqlite_url_for_path(resolved_path)


def _split_directory_list(raw_value: str) -> list[str]:
    normalized = raw_value.replace(";", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _resolve_path(path_value: str | Path, runtime_home: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (runtime_home / candidate).resolve()


def _deduplicate_paths(paths: list[Path]) -> tuple[Path, ...]:
    deduplicated: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(path)
    return tuple(deduplicated)


class ConfigResolver:
    """Resolve runtime configuration from defaults, file, env, DB, and overrides."""

    def __init__(self, extra_overrides: dict[str, Any] | None = None) -> None:
        env_file = _resolve_env_file()
        self._env = EnvironmentSettings(_env_file=env_file)
        self._extra_overrides = extra_overrides or {}

    def resolve(self, db_overrides: dict[str, str] | None = None) -> RuntimeConfig:
        env_values = self._env.model_dump(exclude_none=True)
        configured_runtime_home = env_values.get("runtime_home")
        runtime_home = (
            Path(str(configured_runtime_home)).expanduser()
            if configured_runtime_home
            else get_runtime_home()
        )
        runtime_layout = get_runtime_layout(runtime_home)
        repo_root = get_repo_root()
        built_in_plugin_directory = repo_root / "plugins"
        built_in_theme_directory = repo_root / "themes"

        defaults = {
            "app_name": "Clawgotchi",
            "host": "0.0.0.0",
            "port": 8000,
            "log_level": "INFO",
            "tick_interval_seconds": 2.0,
            "runtime_home": str(runtime_home),
            "database_url": _sqlite_url_for_path(runtime_layout["database_path"]),
            "plugin_directory": str(runtime_layout["plugin_directory"]),
            "theme_directory": str(runtime_layout["theme_directory"]),
            "plugin_directories": "",
            "theme_directories": "",
            "config_file": str((repo_root / "config" / "defaults.toml").resolve()),
            "api_key": "",
            "display_type": "dummy",
            "display_rotation": 0,
            "display_use_partial": False,
            "display_dithering": False,
            "display_debug_write_png": True,
            "display_debug_png_path": str(runtime_layout["cache_directory"] / "clawgotchi_last_frame.png"),
        }

        config_file_path = Path(str(env_values.get("config_file", defaults["config_file"]))).expanduser()
        file_values = self._load_file_values(config_file_path)

        merged: dict[str, Any] = {}
        merged.update(defaults)
        merged.update(file_values)
        merged.update(env_values)

        if db_overrides:
            merged.update(self._normalize_types(db_overrides))

        merged.update(self._extra_overrides)

        final_runtime_home = _resolve_path(str(merged["runtime_home"]), runtime_home)
        final_layout = get_runtime_layout(final_runtime_home)
        database_url = _normalize_sqlite_database_url(str(merged["database_url"]), final_runtime_home)
        plugin_directory = _resolve_path(str(merged["plugin_directory"]), final_runtime_home)
        theme_directory = _resolve_path(str(merged["theme_directory"]), final_runtime_home)
        debug_png_path = _resolve_path(str(merged["display_debug_png_path"]), final_runtime_home)
        configured_plugin_roots = _split_directory_list(str(merged.get("plugin_directories", "")))
        configured_theme_roots = _split_directory_list(str(merged.get("theme_directories", "")))
        plugin_directories = (
            [_resolve_path(path_value, final_runtime_home) for path_value in configured_plugin_roots]
            if configured_plugin_roots
            else [plugin_directory, built_in_plugin_directory.resolve()]
        )
        theme_directories = (
            [_resolve_path(path_value, final_runtime_home) for path_value in configured_theme_roots]
            if configured_theme_roots
            else [theme_directory, built_in_theme_directory.resolve()]
        )
        final_config_file = Path(str(merged["config_file"])).expanduser()

        return RuntimeConfig(
            app_name=str(merged["app_name"]),
            host=str(merged["host"]),
            port=int(merged["port"]),
            log_level=str(merged["log_level"]),
            tick_interval_seconds=float(merged["tick_interval_seconds"]),
            database_url=database_url,
            runtime_home=final_runtime_home,
            logs_directory=final_layout["logs_directory"],
            cache_directory=final_layout["cache_directory"],
            config_directory=final_layout["config_directory"],
            plugin_directory=plugin_directory,
            theme_directory=theme_directory,
            plugin_directories=_deduplicate_paths(plugin_directories),
            theme_directories=_deduplicate_paths(theme_directories),
            built_in_plugin_directory=built_in_plugin_directory.resolve(),
            built_in_theme_directory=built_in_theme_directory.resolve(),
            runtime_env_file=final_layout["runtime_env_file"],
            config_file=final_config_file,
            api_key=str(merged.get("api_key", "")),
            display_type=str(merged["display_type"]),
            display_rotation=int(merged["display_rotation"]),
            display_use_partial=self._coerce_bool(merged["display_use_partial"]),
            display_dithering=self._coerce_bool(merged["display_dithering"]),
            display_debug_write_png=self._coerce_bool(merged["display_debug_write_png"]),
            display_debug_png_path=str(debug_png_path),
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
            if key in {
                "port",
                "display_rotation",
            }:
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
