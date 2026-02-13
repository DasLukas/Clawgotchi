from __future__ import annotations

import json
from pathlib import Path

from app.application.interfaces import ThemeManifest


class FileSystemThemeLoader:
    """Load theme manifests from one or more roots with ordered precedence."""

    def __init__(self, theme_directories: Path | list[Path] | tuple[Path, ...]) -> None:
        if isinstance(theme_directories, Path):
            directories = [theme_directories]
        else:
            directories = list(theme_directories)
        self._theme_directories: list[Path] = []
        seen: set[str] = set()
        for directory in directories:
            resolved = directory.expanduser().resolve()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            self._theme_directories.append(resolved)

    def scan(self) -> list[ThemeManifest]:
        manifests: list[ThemeManifest] = []

        seen_ids: set[str] = set()
        for index, theme_directory in enumerate(self._theme_directories):
            if not theme_directory.exists():
                continue
            source_kind = "runtime" if index == 0 else "builtin"
            for folder in sorted(path for path in theme_directory.iterdir() if path.is_dir()):
                manifest_file = folder / "manifest.json"
                if not manifest_file.exists():
                    continue

                payload = json.loads(manifest_file.read_text(encoding="utf-8"))
                theme_id = str(payload.get("id") or folder.name)
                if theme_id in seen_ids:
                    continue
                manifests.append(
                    ThemeManifest(
                        theme_id=theme_id,
                        name=str(payload.get("name") or theme_id),
                        version=str(payload.get("version") or "0.0.0"),
                        description=str(payload.get("description") or ""),
                        preview=str(payload.get("preview") or ""),
                        stylesheet=str(payload.get("stylesheet") or "assets/style.css"),
                        source_root=str(theme_directory),
                        source_kind=source_kind,
                    )
                )
                seen_ids.add(theme_id)
        return manifests
