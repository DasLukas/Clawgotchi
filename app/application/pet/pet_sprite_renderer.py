from __future__ import annotations

import math
from typing import Any

from PIL import Image

from app.application.render.layout import Rect


class PetSpriteRenderer:
    def __init__(self, theme_loader: Any, default_threshold: int = 128) -> None:
        self._theme_loader = theme_loader
        self._default_threshold = default_threshold

    def render(
        self,
        canvas: Image.Image,
        *,
        theme_id: str,
        manifest: Any,
        animation_name: str,
        frame_index: int,
        content_rect: Rect,
    ) -> None:
        animation = self._resolve_animation(manifest, animation_name)
        frames = list(getattr(animation, "frames", []))
        if not frames:
            return

        frame_path = frames[frame_index % len(frames)]
        frame = self._theme_loader.load_frame(f"{theme_id}/{frame_path}")

        placement = getattr(manifest, "placement", None)
        placement_mode = str(getattr(placement, "mode", "sprite"))

        if placement_mode in {"legacy_fullframe", "fullframe"}:
            self._render_legacy_fullframe(canvas, frame, content_rect)
            return

        self._render_sprite(canvas, frame, manifest=manifest, content_rect=content_rect)

    def _render_legacy_fullframe(self, canvas: Image.Image, frame: Image.Image, content_rect: Rect) -> None:
        prepared = frame.convert("1", dither=Image.NONE)
        if prepared.size != canvas.size:
            prepared = prepared.resize(canvas.size, resample=Image.NEAREST)

        region = prepared.crop(
            (content_rect.x, content_rect.y, content_rect.x + content_rect.w, content_rect.y + content_rect.h)
        )
        canvas.paste(region, (content_rect.x, content_rect.y))

    def _render_sprite(self, canvas: Image.Image, frame: Image.Image, manifest: Any, content_rect: Rect) -> None:
        placement = getattr(manifest, "placement", None)
        render_cfg = getattr(manifest, "render", None)

        base_sprite_size = tuple(getattr(render_cfg, "base_sprite_size", [])) if render_cfg is not None else ()
        if len(base_sprite_size) == 2 and int(base_sprite_size[0]) > 0 and int(base_sprite_size[1]) > 0:
            base_width = int(base_sprite_size[0])
            base_height = int(base_sprite_size[1])
        else:
            base_width, base_height = frame.size

        scale = float(getattr(placement, "scale", 1.0)) if placement is not None else 1.0
        scale_mode = str(getattr(placement, "scale_mode", "integer_only")) if placement is not None else "integer_only"

        if scale_mode == "integer_only":
            scale = max(1.0, float(round(scale)))
        else:
            scale = max(0.1, scale)

        target_width = max(1, int(round(base_width * scale)))
        target_height = max(1, int(round(base_height * scale)))

        fit_scale = min(content_rect.w / target_width, content_rect.h / target_height, 1.0)
        if fit_scale < 1.0:
            target_width = max(1, int(math.floor(target_width * fit_scale)))
            target_height = max(1, int(math.floor(target_height * fit_scale)))

        rgba = frame.convert("RGBA").resize((target_width, target_height), resample=Image.NEAREST)

        anchor = str(getattr(placement, "anchor", "bottom_center")) if placement is not None else "bottom_center"
        offset_x = int(getattr(placement, "offset_x", 0)) if placement is not None else 0
        offset_y = int(getattr(placement, "offset_y", 0)) if placement is not None else 0

        origin_x, origin_y = self._resolve_anchor(anchor=anchor, content_rect=content_rect, width=target_width, height=target_height)
        origin_x += offset_x
        origin_y += offset_y

        origin_x = max(content_rect.x, min(origin_x, content_rect.x + content_rect.w - target_width))
        origin_y = max(content_rect.y, min(origin_y, content_rect.y + content_rect.h - target_height))

        grayscale = Image.new("L", (target_width, target_height), color=255)
        grayscale.paste(rgba.convert("L"), mask=rgba.getchannel("A"))

        threshold = int(getattr(render_cfg, "threshold", self._default_threshold)) if render_cfg is not None else self._default_threshold
        threshold = max(0, min(255, threshold))

        dither_enabled = bool(getattr(render_cfg, "dither", False)) if render_cfg is not None else False
        if dither_enabled:
            mono = grayscale.convert("1")
        else:
            mono = grayscale.point(lambda pixel: 255 if pixel >= threshold else 0, mode="1")

        canvas.paste(mono, (origin_x, origin_y))

    def _resolve_anchor(self, anchor: str, content_rect: Rect, width: int, height: int) -> tuple[int, int]:
        if anchor == "center":
            x = content_rect.x + (content_rect.w - width) // 2
            y = content_rect.y + (content_rect.h - height) // 2
            return x, y

        if anchor == "top_center":
            x = content_rect.x + (content_rect.w - width) // 2
            y = content_rect.y
            return x, y

        if anchor == "bottom_left":
            return content_rect.x, content_rect.y + content_rect.h - height

        if anchor == "bottom_right":
            return content_rect.x + content_rect.w - width, content_rect.y + content_rect.h - height

        # default: bottom_center
        x = content_rect.x + (content_rect.w - width) // 2
        y = content_rect.y + content_rect.h - height
        return x, y

    def _resolve_animation(self, manifest: Any, requested_animation: str) -> Any:
        animations: dict[str, Any] = dict(getattr(manifest, "animations", {}))

        resolved = animations.get(requested_animation)
        if resolved is None or not getattr(resolved, "frames", []):
            default_animation = str(getattr(manifest, "default_animation", "idle"))
            resolved = animations.get(default_animation)

        if resolved is None or not getattr(resolved, "frames", []):
            resolved = animations.get("idle")

        if resolved is None:
            raise ValueError("Theme does not contain any animation frames.")

        return resolved
