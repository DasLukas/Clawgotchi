from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.application.services.render_service import RenderService
from app.domain.models.pet_state import PetState
from app.infrastructure.display.dummy import DummyDisplayDriver
from app.infrastructure.themes.theme_loader import ThemeLoader


def _write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("1", (264, 176), color=1).save(path)


def _build_theme(tmp_path: Path, include_scratch_duration: bool) -> Path:
    themes_root = tmp_path / "themes"
    theme_dir = themes_root / "default"

    _write_image(theme_dir / "assets/idle_0.png")
    _write_image(theme_dir / "assets/idle_1.png")
    _write_image(theme_dir / "assets/idle_2.png")
    _write_image(theme_dir / "assets/scratch_0.png")
    _write_image(theme_dir / "assets/scratch_1.png")

    scratch_animation = {
        "fps": 2.0,
        "frames": ["assets/scratch_0.png", "assets/scratch_1.png"],
    }
    if include_scratch_duration:
        scratch_animation["duration_ms"] = 900

    manifest = {
        "id": "default",
        "name": "Default",
        "placement_mode": "fullframe",
        "canvas_width": 264,
        "canvas_height": 176,
        "default_animation": "idle",
        "animations": {
            "idle": {
                "fps": 0.33,
                "frames": ["assets/idle_0.png", "assets/idle_1.png", "assets/idle_2.png"],
            },
            "scratch": scratch_animation,
        },
    }

    (theme_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return themes_root


def test_idle_animation_frame_progression(tmp_path: Path) -> None:
    themes_root = _build_theme(tmp_path, include_scratch_duration=True)
    loader = ThemeLoader(themes_root)
    display = DummyDisplayDriver(write_debug_png=False)
    render_service = RenderService(theme_loader=loader, display_driver=display, default_theme_id="default")

    pet_state = PetState.create(name="Mochi", emotion="content")
    pet_state.animation_started_ts = 0.0

    decision_t0 = render_service.should_render(pet_state=pet_state, now_ts=0.0)
    decision_t29 = render_service.should_render(pet_state=pet_state, now_ts=2.9)
    decision_t31 = render_service.should_render(pet_state=pet_state, now_ts=3.1)

    assert decision_t0.frame_index == 0
    assert decision_t29.frame_index == 0
    assert decision_t31.frame_index == 1


def test_scratch_duration_fallback_and_frame_progression(tmp_path: Path) -> None:
    themes_root = _build_theme(tmp_path, include_scratch_duration=False)
    loader = ThemeLoader(themes_root)
    display = DummyDisplayDriver(write_debug_png=False)
    render_service = RenderService(theme_loader=loader, display_driver=display, default_theme_id="default")

    pet_state = PetState.create(name="Mochi", emotion="happy")
    pet_state.set_temporary_animation("scratch", duration_ms=1200, now_ts=10.0)

    decision_t10 = render_service.should_render(pet_state=pet_state, now_ts=10.0)
    decision_t106 = render_service.should_render(pet_state=pet_state, now_ts=10.6)

    assert render_service.get_animation_duration_ms("scratch") == 1200
    assert decision_t10.frame_index == 0
    assert decision_t106.frame_index == 1
