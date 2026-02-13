from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any

from app.config import ConfigResolver, ensure_runtime_layout, get_runtime_layout
from app.infrastructure.plugin_loader import FileSystemPluginLoader


@dataclass(slots=True)
class PluginDependencyPlan:
    """Resolved plugin dependency installation plan.

    Attributes:
        plugin_id: Target plugin identifier.
        packages: Python package requirements to install.
        venv_python: Python executable inside the target virtual environment.
        registry_file: Runtime registry file used to persist installation records.
    """

    plugin_id: str
    packages: list[str]
    venv_python: Path
    registry_file: Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry(registry_file: Path) -> dict[str, Any]:
    """Load plugin dependency registry JSON.

    Parameters:
        registry_file: Registry file path.

    Returns:
        Parsed registry payload, or an empty scaffold when missing/invalid.
    """

    if not registry_file.exists():
        return {"version": 1, "updated_at": _utc_now_iso(), "plugins": {}}
    try:
        payload = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": _utc_now_iso(), "plugins": {}}

    if not isinstance(payload, dict):
        return {"version": 1, "updated_at": _utc_now_iso(), "plugins": {}}
    if "plugins" not in payload or not isinstance(payload["plugins"], dict):
        payload["plugins"] = {}
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", _utc_now_iso())
    return payload


def _save_registry(registry_file: Path, payload: dict[str, Any]) -> None:
    """Persist plugin dependency registry JSON atomically.

    Parameters:
        registry_file: Destination registry file path.
        payload: Registry payload to write.
    """

    registry_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = registry_file.with_suffix(".tmp")
    temp_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_file.replace(registry_file)


def _is_venv_python(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _candidate_venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _resolve_venv_python(runtime_home: Path, explicit_venv: str | None = None) -> Path:
    """Resolve the Python executable used for plugin dependency installs.

    Resolution order:
    1. Explicit `--venv`
    2. Current interpreter when already inside a virtual environment
    3. `CLAW_VENV_PATH`
    4. Runtime venv (`<runtime_home>/venv`)
    5. Runtime venv (`<runtime_home>/.venv`)

    Parameters:
        runtime_home: Runtime home used to find default venv locations.
        explicit_venv: Optional explicit virtual environment path.

    Returns:
        Path to the virtualenv python executable.

    Raises:
        RuntimeError: If no virtualenv python executable can be resolved.
    """

    if explicit_venv:
        explicit_path = _candidate_venv_python(Path(explicit_venv).expanduser())
        if _is_venv_python(explicit_path):
            return explicit_path
        raise RuntimeError(f"Provided venv path does not contain a Python executable: {explicit_path}")

    if hasattr(sys, "base_prefix") and sys.prefix != sys.base_prefix:
        return Path(sys.executable).resolve()

    configured_venv = os.environ.get("CLAW_VENV_PATH")
    if configured_venv:
        configured_python = _candidate_venv_python(Path(configured_venv).expanduser())
        if _is_venv_python(configured_python):
            return configured_python

    for suffix in ("venv", ".venv"):
        candidate = _candidate_venv_python(runtime_home / suffix)
        if _is_venv_python(candidate):
            return candidate

    raise RuntimeError(
        "No virtual environment was found. "
        "Run the bootstrap installer first or pass --venv <path>."
    )


def _extract_package_list(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        return [raw_value.strip()] if raw_value.strip() else []
    if isinstance(raw_value, list):
        packages = [str(item).strip() for item in raw_value if str(item).strip()]
        return list(dict.fromkeys(packages))
    return []


def _resolve_plugin_plan(plugin_id: str, explicit_venv: str | None = None) -> PluginDependencyPlan:
    """Resolve plugin dependency installation plan for a plugin ID.

    Parameters:
        plugin_id: Plugin identifier to resolve.
        explicit_venv: Optional explicit virtual environment path.

    Returns:
        A `PluginDependencyPlan` with resolved packages and install targets.

    Raises:
        ValueError: If the plugin is unknown.
        RuntimeError: If no compatible virtual environment is available.
    """

    resolver = ConfigResolver()
    config = resolver.resolve()
    ensure_runtime_layout(config.runtime_home)
    layout = get_runtime_layout(config.runtime_home)

    manifests = FileSystemPluginLoader(config.plugin_directories).scan()
    manifest_by_id = {manifest.plugin_id: manifest for manifest in manifests}
    if plugin_id not in manifest_by_id:
        raise ValueError(f"Plugin '{plugin_id}' was not found.")

    manifest = manifest_by_id[plugin_id]
    packages = (
        _extract_package_list(manifest.metadata.get("python_dependencies"))
        or _extract_package_list(manifest.metadata.get("pip_dependencies"))
        or _extract_package_list(manifest.metadata.get("dependencies"))
    )
    if not packages:
        raise ValueError(
            f"Plugin '{plugin_id}' does not declare Python dependencies. "
            "Use manifest key 'python_dependencies' to declare them."
        )

    venv_python = _resolve_venv_python(config.runtime_home, explicit_venv=explicit_venv)
    registry_file = layout["plugin_registry_file"]

    return PluginDependencyPlan(
        plugin_id=plugin_id,
        packages=packages,
        venv_python=venv_python,
        registry_file=registry_file,
    )


def _run_pip_install(plan: PluginDependencyPlan, dry_run: bool = False) -> None:
    """Install plugin dependencies into the resolved virtual environment.

    Parameters:
        plan: Resolved installation plan.
        dry_run: When true, print command without installing.

    Raises:
        RuntimeError: If pip install fails.
    """

    command = [str(plan.venv_python), "-m", "pip", "install", *plan.packages]
    if dry_run:
        print("Dry run:", " ".join(command))
        return

    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or f"exit={completed.returncode}"
        raise RuntimeError(f"pip install failed: {details}")

    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)


def _record_install(plan: PluginDependencyPlan) -> None:
    """Record successful dependency installation in runtime registry.

    Parameters:
        plan: Resolved installation plan.
    """

    payload = _load_registry(plan.registry_file)
    payload["plugins"][plan.plugin_id] = {
        "packages": list(plan.packages),
        "installed_at": _utc_now_iso(),
        "venv_python": str(plan.venv_python),
    }
    payload["updated_at"] = _utc_now_iso()
    _save_registry(plan.registry_file, payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install plugin Python dependencies into Clawgotchi venv.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    install_parser = subcommands.add_parser("install", help="Install dependency set for a plugin.")
    install_parser.add_argument("plugin_id", help="Plugin identifier from manifest 'id'.")
    install_parser.add_argument("--venv", dest="venv_path", help="Override venv path if auto-detection is not possible.")
    install_parser.add_argument("--dry-run", action="store_true", help="Show planned pip command without executing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for plugin dependency installation.

    Parameters:
        argv: Optional CLI argument list.

    Returns:
        Exit code (`0` for success, non-zero on failure).

    Usage example:
        `python -m clawgotchi.tools.plugin_deps install example_fun`
    """

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "install":
        parser.error("Unsupported command.")

    try:
        plan = _resolve_plugin_plan(args.plugin_id, explicit_venv=args.venv_path)
        _run_pip_install(plan=plan, dry_run=args.dry_run)
        if not args.dry_run:
            _record_install(plan)
            print(f"Dependencies installed for plugin '{plan.plugin_id}'.")
            print(f"Registry updated: {plan.registry_file}")
    except Exception as exc:
        print(f"Plugin dependency install failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
