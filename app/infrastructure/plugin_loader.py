from __future__ import annotations

import importlib.util
import json
import sys
import logging
from pathlib import Path

from app.application.interfaces import PluginBase, PluginManifest

logger = logging.getLogger(__name__)


class FileSystemPluginLoader:
    def __init__(self, plugin_directory: Path) -> None:
        self._plugin_directory = plugin_directory

    def scan(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        if not self._plugin_directory.exists():
            return manifests

        manifest_files = sorted(self._plugin_directory.rglob("manifest.json"))
        seen_ids: set[str] = set()
        for manifest_file in manifest_files:
            folder = manifest_file.parent

            payload = json.loads(manifest_file.read_text(encoding="utf-8"))
            plugin_id = str(payload.get("id") or folder.name)
            if plugin_id in seen_ids:
                logger.warning("Duplicate plugin id found in filesystem scan; skipping later manifest.", extra={"plugin_id": plugin_id})
                continue

            reserved_keys = {
                "id",
                "name",
                "version",
                "description",
                "entrypoint",
                "class_name",
                "capabilities",
            }
            metadata = {key: value for key, value in payload.items() if key not in reserved_keys}
            relative_directory = folder.relative_to(self._plugin_directory)
            manifests.append(
                PluginManifest(
                    plugin_id=plugin_id,
                    name=str(payload.get("name") or plugin_id),
                    version=str(payload.get("version") or "0.0.0"),
                    description=str(payload.get("description") or ""),
                    entrypoint=str(payload.get("entrypoint") or "plugin.py"),
                    class_name=str(payload.get("class_name") or "Plugin"),
                    directory=str(relative_directory),
                    capabilities=list(payload.get("capabilities") or []),
                    metadata=metadata,
                )
            )
            seen_ids.add(plugin_id)
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> PluginBase:
        plugin_root = self._plugin_directory / manifest.directory
        plugin_path = plugin_root / manifest.entrypoint
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin entrypoint was not found: {plugin_path}")

        module_name = f"clawgotchi_plugin_{manifest.plugin_id}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module for plugin '{manifest.plugin_id}'.")

        plugin_root_str = str(plugin_root)
        if plugin_root_str not in sys.path:
            sys.path.insert(0, plugin_root_str)

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        plugin_type = getattr(module, manifest.class_name, None)
        if plugin_type is None:
            raise ImportError(
                f"Plugin '{manifest.plugin_id}' does not define class '{manifest.class_name}'."
            )

        instance = plugin_type()
        if not isinstance(instance, PluginBase):
            raise TypeError(
                f"Plugin '{manifest.plugin_id}' class '{manifest.class_name}' must inherit PluginBase."
            )
        return instance
