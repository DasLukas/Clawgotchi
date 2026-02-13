from __future__ import annotations

import json
from pathlib import Path

from app.infrastructure.plugin_loader import FileSystemPluginLoader


def test_plugin_loader_scans_nested_plugin_directories(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "hardware" / "example_hw"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "example_hw",
                "name": "Example HW",
                "version": "0.1.0",
                "entrypoint": "plugin.py",
                "class_name": "Plugin",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "from app.application.interfaces import PluginBase\n\nclass Plugin(PluginBase):\n    pass\n",
        encoding="utf-8",
    )

    loader = FileSystemPluginLoader(tmp_path / "plugins")
    manifests = loader.scan()

    assert len(manifests) == 1
    assert manifests[0].plugin_id == "example_hw"
    assert manifests[0].directory == "hardware/example_hw"

    instance = loader.load_plugin(manifests[0])
    assert instance.plugin_id == "base"


def test_plugin_loader_prefers_runtime_root_when_ids_overlap(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-plugins"
    builtin_root = tmp_path / "builtin-plugins"

    runtime_shared = runtime_root / "shared"
    runtime_shared.mkdir(parents=True, exist_ok=True)
    (runtime_shared / "manifest.json").write_text(
        json.dumps(
            {
                "id": "shared",
                "name": "Shared Runtime Plugin",
                "version": "1.0.0",
                "entrypoint": "plugin.py",
                "class_name": "Plugin",
            }
        ),
        encoding="utf-8",
    )
    (runtime_shared / "plugin.py").write_text(
        "from app.application.interfaces import PluginBase\n\nclass Plugin(PluginBase):\n    plugin_id = 'runtime_shared'\n",
        encoding="utf-8",
    )

    builtin_shared = builtin_root / "shared"
    builtin_shared.mkdir(parents=True, exist_ok=True)
    (builtin_shared / "manifest.json").write_text(
        json.dumps(
            {
                "id": "shared",
                "name": "Shared Builtin Plugin",
                "version": "9.9.9",
                "entrypoint": "plugin.py",
                "class_name": "Plugin",
            }
        ),
        encoding="utf-8",
    )
    (builtin_shared / "plugin.py").write_text(
        "from app.application.interfaces import PluginBase\n\nclass Plugin(PluginBase):\n    plugin_id = 'builtin_shared'\n",
        encoding="utf-8",
    )

    builtin_only = builtin_root / "builtin_only"
    builtin_only.mkdir(parents=True, exist_ok=True)
    (builtin_only / "manifest.json").write_text(
        json.dumps(
            {
                "id": "builtin_only",
                "name": "Builtin Only Plugin",
                "version": "0.2.0",
                "entrypoint": "plugin.py",
                "class_name": "Plugin",
            }
        ),
        encoding="utf-8",
    )
    (builtin_only / "plugin.py").write_text(
        "from app.application.interfaces import PluginBase\n\nclass Plugin(PluginBase):\n    plugin_id = 'builtin_only'\n",
        encoding="utf-8",
    )

    loader = FileSystemPluginLoader([runtime_root, builtin_root])
    manifests = loader.scan()
    manifest_by_id = {manifest.plugin_id: manifest for manifest in manifests}

    assert manifest_by_id["shared"].name == "Shared Runtime Plugin"
    assert manifest_by_id["shared"].source_kind == "runtime"
    assert manifest_by_id["builtin_only"].source_kind == "builtin"

    instance = loader.load_plugin(manifest_by_id["shared"])
    assert instance.plugin_id == "runtime_shared"
