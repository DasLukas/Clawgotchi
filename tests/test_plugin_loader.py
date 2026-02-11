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
