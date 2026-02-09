from __future__ import annotations

import json
from pathlib import Path

from app.application.interfaces import ThemeManifest


class FileSystemThemeLoader:
    def __init__(self, theme_directory: Path) -> None:
        self._theme_directory = theme_directory

    def scan(self) -> list[ThemeManifest]:
        manifests: list[ThemeManifest] = []
        if not self._theme_directory.exists():
            return manifests

        for folder in sorted(path for path in self._theme_directory.iterdir() if path.is_dir()):
            manifest_file = folder / "manifest.json"
            if not manifest_file.exists():
                continue

            payload = json.loads(manifest_file.read_text(encoding="utf-8"))
            theme_id = str(payload.get("id") or folder.name)
            manifests.append(
                ThemeManifest(
                    theme_id=theme_id,
                    name=str(payload.get("name") or theme_id),
                    version=str(payload.get("version") or "0.0.0"),
                    description=str(payload.get("description") or ""),
                    preview=str(payload.get("preview") or ""),
                    stylesheet=str(payload.get("stylesheet") or "assets/style.css"),
                )
            )
        return manifests
