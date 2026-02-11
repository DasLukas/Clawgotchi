from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Protocol

from PIL import Image

from app.application.input.router import InputRouter
from app.application.pet.pet_sprite_renderer import PetSpriteRenderer
from app.application.ports.display import DisplayCapabilities
from app.application.render.layout import LayoutCalculator
from app.application.render.screen_renderer import MenuSidebarRenderer, RenderPayload, ScreenRenderer
from app.application.ui.menu_controller import MenuController, MenuSnapshot
from app.domain.models.pet_state import PetState
from app.domain.ui.menu import MenuEntry
from core.display_manager import DisplayManager
from core.framebuffer import FrameBuffer1Bit

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

    def __init__(
        self,
        theme_loader: ThemeLoaderPort,
        framebuffer: FrameBuffer1Bit,
        display_manager: DisplayManager,
        display_capabilities: DisplayCapabilities,
        input_router: InputRouter,
        menu_controller: MenuController,
        default_theme_id: str = "default",
    ) -> None:
        self._theme_loader = theme_loader
        self._framebuffer = framebuffer
        self._display_manager = display_manager
        self._display_capabilities = display_capabilities
        self._active_theme_id = default_theme_id
        self._input_router = input_router
        self._menu_controller = menu_controller
        self._pending_menu_actions: list[str] = []

        self._screen_renderer = ScreenRenderer(
            layout_calculator=LayoutCalculator(),
            menu_sidebar_renderer=MenuSidebarRenderer(),
            pet_sprite_renderer=PetSpriteRenderer(theme_loader=theme_loader),
        )

    def set_theme(self, theme_id: str) -> None:
        self._active_theme_id = theme_id

    def set_display_context(self, framebuffer: FrameBuffer1Bit, capabilities: DisplayCapabilities) -> None:
        self._framebuffer = framebuffer
        self._display_capabilities = capabilities

    def get_framebuffer(self) -> FrameBuffer1Bit:
        return self._framebuffer

    def get_display_capabilities(self) -> DisplayCapabilities:
        return self._display_capabilities

    def get_menu_snapshot(self) -> MenuSnapshot:
        return self._menu_controller.get_snapshot()

    def register_menu_root_item(self, item: MenuEntry) -> None:
        self._menu_controller.register_root_item(item)

    def process_input_events(self, max_events: int = 32) -> bool:
        changed = False
        for event in self._input_router.drain(max_events=max_events):
            if self._menu_controller.handle_event(event):
                changed = True

        new_actions = self._menu_controller.consume_pending_actions()
        if new_actions:
            self._pending_menu_actions.extend(new_actions)
            changed = True

        return changed

    def consume_menu_actions(self) -> list[str]:
        actions = list(self._pending_menu_actions)
        self._pending_menu_actions.clear()
        return actions

    def should_render(self, pet_state: PetState, now_ts: float) -> RenderDecision:
        manifest = self._safe_load_manifest(self._active_theme_id)
        animation_name, animation_config = self._resolve_animation(manifest, pet_state.current_animation)
        frame_index = self._compute_frame_index(
            pet_state=pet_state,
            animation=animation_name,
            animation_config=animation_config,
            now_ts=now_ts,
        )
        frame_changed = frame_index != pet_state.animation_frame_index

        min_interval_ms = 1000 if animation_name == "scratch" else 2800
        if pet_state.last_render_ts is None:
            return RenderDecision(True, True, frame_index, min_interval_ms, animation_name)

        elapsed_ms = int((now_ts - pet_state.last_render_ts) * 1000)
        should_render = frame_changed or elapsed_ms >= min_interval_ms
        return RenderDecision(should_render, frame_changed, frame_index, min_interval_ms, animation_name)

    def render_frame(self, pet_state: PetState, now_ts: float) -> bool:
        manifest = self._safe_load_manifest(self._active_theme_id)
        animation_name, animation_config = self._resolve_animation(manifest, pet_state.current_animation)
        frame_index = self._compute_frame_index(
            pet_state=pet_state,
            animation=animation_name,
            animation_config=animation_config,
            now_ts=now_ts,
        )

        changed = self._screen_renderer.render(
            framebuffer=self._framebuffer,
            capabilities=self._display_capabilities,
            payload=RenderPayload(
                theme_id=self._active_theme_id,
                manifest=manifest,
                animation_name=animation_name,
                frame_index=frame_index,
            ),
            menu_controller=self._menu_controller,
        )

        pet_state.mark_rendered(now_ts=now_ts, frame_index=frame_index)
        return changed

    def push_framebuffer(self) -> None:
        self._display_manager.push(self._framebuffer)

    def push_image(self, image: Image.Image) -> bool:
        changed = self._framebuffer.replace_from_image(image)
        self.push_framebuffer()
        return changed

    def get_last_frame(self) -> Image.Image:
        return self._framebuffer.to_pil_image()

    def get_last_frame_png(self) -> bytes:
        return self._framebuffer.to_png_bytes()

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
