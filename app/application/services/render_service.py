from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import logging
from typing import Any, Protocol

from PIL import Image

from app.application.ports.display import DisplayDriver, Frame
from app.domain.models.pet_state import PetState

logger = logging.getLogger(__name__)


class ThemeLoaderPort(Protocol):
    def load(self, theme_id: str) -> Any:
        ...

    def load_frame(self, path: str) -> Image.Image:
        ...


@dataclass(slots=True)
class RenderDecision:
    should_render: bool
    frame_changed: bool
    frame_index: int
    min_interval_ms: int
    animation: str


class RenderService:
    SCRATCH_DEFAULT_DURATION_MS = 1200
    IDLE_DEFAULT_FPS = 0.33

    def __init__(self, theme_loader: ThemeLoaderPort, display_driver: DisplayDriver, default_theme_id: str = "default") -> None:
        self._theme_loader = theme_loader
        self._display_driver = display_driver
        self._active_theme_id = default_theme_id
        self._last_image: Image.Image | None = None

    def set_theme(self, theme_id: str) -> None:
        self._active_theme_id = theme_id

    def should_render(self, pet_state: PetState, now_ts: float) -> RenderDecision:
        manifest = self._safe_load_manifest(self._active_theme_id)
        animation_name, animation_config = self._resolve_animation(manifest, pet_state.current_animation)
        frame_index = self._compute_frame_index(pet_state=pet_state, animation=animation_name, animation_config=animation_config, now_ts=now_ts)
        frame_changed = frame_index != pet_state.animation_frame_index

        min_interval_ms = 1000 if animation_name == "scratch" else 2800
        if pet_state.last_render_ts is None:
            return RenderDecision(True, True, frame_index, min_interval_ms, animation_name)

        elapsed_ms = int((now_ts - pet_state.last_render_ts) * 1000)
        should_render = frame_changed or elapsed_ms >= min_interval_ms
        return RenderDecision(should_render, frame_changed, frame_index, min_interval_ms, animation_name)

    def render_frame(self, pet_state: PetState, now_ts: float) -> Image.Image:
        manifest = self._safe_load_manifest(self._active_theme_id)
        animation_name, animation_config = self._resolve_animation(manifest, pet_state.current_animation)
        frame_index = self._compute_frame_index(pet_state=pet_state, animation=animation_name, animation_config=animation_config, now_ts=now_ts)

        frame_path = animation_config.frames[frame_index] if animation_config.frames else None
        capabilities = self._display_driver.get_capabilities()
        canvas = Image.new("1", (capabilities.width, capabilities.height), color=1)

        if frame_path:
            try:
                source = self._theme_loader.load_frame(f"{self._active_theme_id}/{frame_path}")
                source_1bit = source.convert("1", dither=Image.NONE)
                if manifest.placement_mode == "fullframe":
                    if source_1bit.size != (manifest.canvas_width, manifest.canvas_height):
                        source_1bit = source_1bit.resize((manifest.canvas_width, manifest.canvas_height))
                    canvas.paste(source_1bit, (0, 0))
                else:
                    canvas.paste(source_1bit, (0, 0))
            except Exception:
                logger.exception("Failed to load frame asset", extra={"theme_id": self._active_theme_id, "frame": frame_path})

        pet_state.mark_rendered(now_ts=now_ts, frame_index=frame_index)
        self._last_image = canvas.copy()
        return canvas

    def push_frame(self, image: Image.Image) -> None:
        self._display_driver.render(Frame(image=image))
        self._last_image = image.copy()

    def get_last_frame(self) -> Image.Image | None:
        if self._last_image is None:
            return None
        return self._last_image.copy()

    def get_last_frame_png(self) -> bytes | None:
        image = self.get_last_frame()
        if image is None:
            return None

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def get_animation_duration_ms(self, animation: str) -> int:
        manifest = self._safe_load_manifest(self._active_theme_id)
        _, animation_config = self._resolve_animation(manifest, animation)
        if animation_config.duration_ms is not None:
            return int(animation_config.duration_ms)
        if animation == "scratch":
            return self.SCRATCH_DEFAULT_DURATION_MS
        return 0

    def _safe_load_manifest(self, theme_id: str) -> Any:
        try:
            return self._theme_loader.load(theme_id)
        except Exception:
            logger.exception("Failed to load active theme, falling back to default theme", extra={"theme_id": theme_id})
            self._active_theme_id = "default"
            return self._theme_loader.load("default")

    def _resolve_animation(self, manifest: Any, requested_animation: str) -> tuple[str, Any]:
        animations: dict[str, Any] = dict(getattr(manifest, "animations", {}))

        resolved_animation = requested_animation
        resolved = animations.get(resolved_animation)

        if resolved is None or not getattr(resolved, "frames", []):
            resolved_animation = getattr(manifest, "default_animation", "idle")
            resolved = animations.get(resolved_animation)

        if resolved is None or not getattr(resolved, "frames", []):
            resolved_animation = "idle"
            resolved = animations.get("idle")

        if resolved is None:
            raise ValueError(f"Theme '{self._active_theme_id}' does not define any animation frames.")

        return resolved_animation, resolved

    def _compute_frame_index(self, pet_state: PetState, animation: str, animation_config: Any, now_ts: float) -> int:
        frames = list(getattr(animation_config, "frames", []))
        if not frames:
            return 0
        if len(frames) == 1:
            return 0

        fps = float(getattr(animation_config, "fps", self.IDLE_DEFAULT_FPS if animation == "idle" else 1.0))
        if fps <= 0:
            fps = self.IDLE_DEFAULT_FPS if animation == "idle" else 1.0

        if pet_state.animation_started_ts is None:
            pet_state.animation_started_ts = now_ts

        elapsed_seconds = max(0.0, now_ts - pet_state.animation_started_ts)
        return int(elapsed_seconds * fps) % len(frames)
