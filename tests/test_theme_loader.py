from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from app.infrastructure.theme_loader import FileSystemThemeLoader
from app.infrastructure.themes.theme_loader import ThemeLoader


def _write_image(path: Path, width: int = 264, height: int = 176) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("1", (width, height), color=1).save(path)


def _write_manifest(theme_dir: Path, payload: dict) -> None:
    (theme_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_theme_loader_parses_manifest_and_loads_frame(tmp_path: Path) -> None:
    themes_root = tmp_path / "themes"
    theme_dir = themes_root / "default"
    _write_image(theme_dir / "assets/idle_0.png")
    _write_image(theme_dir / "assets/idle_1.png")
    _write_image(theme_dir / "assets/scratch_0.png")

    _write_manifest(
        theme_dir,
        {
            "id": "default",
            "name": "Default",
            "placement_mode": "fullframe",
            "canvas_width": 264,
            "canvas_height": 176,
            "default_animation": "idle",
            "animations": {
                "idle": {"fps": 0.33, "frames": ["assets/idle_0.png", "assets/idle_1.png"]},
                "scratch": {"fps": 2.0, "frames": ["assets/scratch_0.png"]},
            },
        },
    )

    loader = ThemeLoader(themes_root)
    manifest = loader.load("default")
    frame = loader.load_frame("default/assets/idle_0.png")

    assert manifest.id == "default"
    assert manifest.canvas_width == 264
    assert manifest.canvas_height == 176
    assert frame.size == (264, 176)


def test_theme_loader_rejects_invalid_fullframe_size(tmp_path: Path) -> None:
    themes_root = tmp_path / "themes"
    theme_dir = themes_root / "default"
    _write_image(theme_dir / "assets/idle_0.png", width=120, height=176)

    _write_manifest(
        theme_dir,
        {
            "id": "default",
            "name": "Default",
            "placement_mode": "fullframe",
            "canvas_width": 264,
            "canvas_height": 176,
            "animations": {
                "idle": {"fps": 0.33, "frames": ["assets/idle_0.png"]},
            },
        },
    )

    loader = ThemeLoader(themes_root)
    with pytest.raises(ValueError):
        loader.load("default")


def test_theme_registry_loader_prefers_runtime_root_on_duplicate_ids(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-themes"
    builtin_root = tmp_path / "builtin-themes"

    runtime_theme = runtime_root / "default"
    runtime_theme.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        runtime_theme,
        {
            "id": "default",
            "name": "Runtime Default",
            "version": "1.0.0",
            "stylesheet": "assets/style.css",
        },
    )
    (runtime_theme / "assets").mkdir(parents=True, exist_ok=True)

    builtin_theme = builtin_root / "default"
    builtin_theme.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        builtin_theme,
        {
            "id": "default",
            "name": "Builtin Default",
            "version": "9.9.9",
            "stylesheet": "assets/style.css",
        },
    )
    (builtin_theme / "assets").mkdir(parents=True, exist_ok=True)

    builtin_only = builtin_root / "classic"
    builtin_only.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        builtin_only,
        {
            "id": "classic",
            "name": "Classic",
            "version": "0.2.0",
            "stylesheet": "assets/style.css",
        },
    )
    (builtin_only / "assets").mkdir(parents=True, exist_ok=True)

    loader = FileSystemThemeLoader([runtime_root, builtin_root])
    manifests = loader.scan()
    manifest_by_id = {manifest.theme_id: manifest for manifest in manifests}

    assert manifest_by_id["default"].name == "Runtime Default"
    assert manifest_by_id["default"].source_kind == "runtime"
    assert manifest_by_id["classic"].source_kind == "builtin"


def test_theme_loader_falls_back_to_builtin_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-themes"
    builtin_root = tmp_path / "builtin-themes"
    runtime_root.mkdir(parents=True, exist_ok=True)

    default_theme = builtin_root / "default"
    _write_image(default_theme / "assets/idle_0.png")
    _write_manifest(
        default_theme,
        {
            "id": "default",
            "name": "Default",
            "placement_mode": "fullframe",
            "canvas_width": 264,
            "canvas_height": 176,
            "animations": {
                "idle": {"fps": 1.0, "frames": ["assets/idle_0.png"]},
            },
        },
    )

    loader = ThemeLoader([runtime_root, builtin_root])
    manifest = loader.load("default")
    frame = loader.load_frame("default/assets/idle_0.png")

    assert manifest.name == "Default"
    assert frame.size == (264, 176)
