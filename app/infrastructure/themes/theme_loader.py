from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ThemeAnimation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fps: float = 1.0
    frames: list[str] = Field(default_factory=list)
    duration_ms: int | None = None

    @field_validator("fps")
    @classmethod
    def validate_fps(cls, value: float) -> float:
        if value <= 0:
            return 1.0
        return value


class ThemeManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    preview: str = ""
    stylesheet: str = "assets/style.css"
    placement_mode: str = "fullframe"
    canvas_width: int = 264
    canvas_height: int = 176
    default_animation: str = "idle"
    animations: dict[str, ThemeAnimation] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_placement(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if "placement_mode" in value:
            return value

        placement = value.get("placement")
        if isinstance(placement, dict):
            mode = placement.get("mode")
            if isinstance(mode, str):
                value["placement_mode"] = mode
        return value


class ThemeLoader:
    def __init__(self, themes_root: Path) -> None:
        self._themes_root = themes_root
        self._manifest_cache: dict[str, ThemeManifest] = {}
        self._frame_cache: dict[str, Image.Image] = {}

    def load(self, theme_id: str) -> ThemeManifest:
        if theme_id in self._manifest_cache:
            return self._manifest_cache[theme_id]

        manifest_path = self._themes_root / theme_id / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Theme manifest was not found: {manifest_path}")

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ThemeManifest.model_validate(payload)
        self._validate_manifest_assets(theme_id=theme_id, manifest=manifest)
        self._manifest_cache[theme_id] = manifest
        return manifest

    def load_frame(self, path: str) -> Image.Image:
        requested_path = Path(path)
        resolved = requested_path if requested_path.is_absolute() else self._themes_root / requested_path
        cache_key = str(resolved.resolve())

        if cache_key in self._frame_cache:
            return self._frame_cache[cache_key].copy()

        if not resolved.exists():
            raise FileNotFoundError(f"Theme frame was not found: {resolved}")

        with Image.open(resolved) as source:
            source.load()
            image = source.copy()
        self._frame_cache[cache_key] = image
        return image.copy()

    def invalidate_cache(self, theme_id: str | None = None) -> None:
        if theme_id is None:
            self._manifest_cache.clear()
            self._frame_cache.clear()
            return

        self._manifest_cache.pop(theme_id, None)
        prefix = str((self._themes_root / theme_id).resolve())
        for key in list(self._frame_cache.keys()):
            if key.startswith(prefix):
                self._frame_cache.pop(key, None)

    def _validate_manifest_assets(self, theme_id: str, manifest: ThemeManifest) -> None:
        if manifest.placement_mode != "fullframe":
            return

        for animation in manifest.animations.values():
            for frame in animation.frames:
                image = self.load_frame(f"{theme_id}/{frame}")
                if image.width != manifest.canvas_width or image.height != manifest.canvas_height:
                    raise ValueError(
                        "Theme frame dimensions do not match fullframe canvas: "
                        f"expected {manifest.canvas_width}x{manifest.canvas_height}, "
                        f"got {image.width}x{image.height}."
                    )
