from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

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
