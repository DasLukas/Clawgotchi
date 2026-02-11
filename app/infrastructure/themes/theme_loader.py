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


class ThemeRenderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_sprite_size: list[int] = Field(default_factory=list)
    dither: bool = False
    threshold: int = 128

    @field_validator("base_sprite_size")
    @classmethod
    def validate_base_sprite_size(cls, value: list[int]) -> list[int]:
        if not value:
            return value
        if len(value) != 2:
            raise ValueError("render.base_sprite_size must contain exactly two integers: [width, height].")
        width, height = int(value[0]), int(value[1])
        if width <= 0 or height <= 0:
            raise ValueError("render.base_sprite_size values must be positive.")
        return [width, height]

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, value: int) -> int:
        return max(0, min(255, int(value)))


class ThemePlacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = "sprite"
    anchor: str = "bottom_center"
    offset_x: int = 0
    offset_y: int = 0
    scale_mode: str = "integer_only"
    scale: float = 1.0

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "fullframe":
            return "legacy_fullframe"
        if normalized not in {"sprite", "legacy_fullframe"}:
            return "sprite"
        return normalized

    @field_validator("scale_mode")
    @classmethod
    def validate_scale_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"integer_only", "free"}:
            return "integer_only"
        return normalized

    @field_validator("scale")
    @classmethod
    def validate_scale(cls, value: float) -> float:
        return max(0.1, float(value))


class ThemeManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    preview: str = ""
    stylesheet: str = "assets/style.css"
    canvas_width: int = 264
    canvas_height: int = 176
    default_animation: str = "idle"
    render: ThemeRenderConfig = Field(default_factory=ThemeRenderConfig)
    placement: ThemePlacement = Field(default_factory=ThemePlacement)
    animations: dict[str, ThemeAnimation] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        payload = dict(value)

        if "placement" not in payload:
            placement_mode = payload.get("placement_mode")
            if isinstance(placement_mode, str):
                payload["placement"] = {"mode": placement_mode}

        placement = payload.get("placement")
        if isinstance(placement, dict) and "mode" not in placement:
            placement_mode = payload.get("placement_mode")
            if isinstance(placement_mode, str):
                placement["mode"] = placement_mode

        return payload

    @property
    def placement_mode(self) -> str:
        return self.placement.mode


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
        for animation in manifest.animations.values():
            for frame in animation.frames:
                image = self.load_frame(f"{theme_id}/{frame}")

                if manifest.placement.mode != "legacy_fullframe":
                    continue

                if image.width != manifest.canvas_width or image.height != manifest.canvas_height:
                    raise ValueError(
                        "Theme frame dimensions do not match fullframe canvas: "
                        f"expected {manifest.canvas_width}x{manifest.canvas_height}, "
                        f"got {image.width}x{image.height}."
                    )
