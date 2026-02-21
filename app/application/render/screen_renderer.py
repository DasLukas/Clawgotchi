from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from app.application.pet.pet_sprite_renderer import PetSpriteRenderer
from app.application.render.layout import LayoutCalculator, ScreenLayout
from app.application.ports.display import DisplayCapabilities
from app.application.ui.menu_controller import MenuController
from core.framebuffer import FrameBuffer1Bit


@dataclass(slots=True)
class RenderPayload:
    theme_id: str
    manifest: object
    animation_name: str
    frame_index: int


class MenuBarRenderer:
    def __init__(self, horizontal_padding: int = 3, slot_gap: int = 2, min_slot_width: int = 24) -> None:
        self._horizontal_padding = max(1, horizontal_padding)
        self._slot_gap = max(1, slot_gap)
        self._min_slot_width = max(10, min_slot_width)

    def render(self, canvas: Image.Image, layout: ScreenLayout, menu_controller: MenuController) -> None:
        draw = ImageDraw.Draw(canvas)
        menu = layout.menu_rect
        x0 = menu.x
        y0 = menu.y
        x1 = menu.x + menu.w - 1
        y1 = menu.y + menu.h - 1

        draw.rectangle((x0, y0, x1, y1), fill=1)
        draw.line((x0, y0, x1, y0), fill=0, width=1)

        snapshot = menu_controller.get_snapshot()
        if not snapshot.items:
            return

        max_visible = self._compute_max_visible_slots(menu.w)
        visible_count = min(len(snapshot.items), max_visible)
        start_index = self._resolve_window_start(
            item_count=len(snapshot.items),
            selection_index=snapshot.selection_index,
            visible_count=visible_count,
        )
        visible_items = snapshot.items[start_index : start_index + visible_count]

        inner_x0 = x0 + self._horizontal_padding
        inner_x1 = x1 - self._horizontal_padding
        inner_width = max(1, inner_x1 - inner_x0 + 1)
        gaps_total = (visible_count - 1) * self._slot_gap
        slot_width = max(1, (inner_width - gaps_total) // visible_count)
        used_width = visible_count * slot_width + gaps_total
        cursor_x = inner_x0 + max(0, (inner_width - used_width) // 2)

        for idx, item_label in enumerate(visible_items):
            absolute_index = start_index + idx
            selected = absolute_index == snapshot.selection_index
            slot_x0 = cursor_x
            slot_x1 = min(x1 - 1, slot_x0 + slot_width - 1)
            slot_y0 = y0 + 1
            slot_y1 = y1 - 1

            if selected:
                draw.rectangle((slot_x0, slot_y0, slot_x1, slot_y1), fill=0)
                icon_fill = 1
            else:
                draw.rectangle((slot_x0, slot_y0, slot_x1, slot_y1), fill=1, outline=0)
                icon_fill = 0

            icon_margin_x = max(2, slot_width // 5)
            icon_margin_y = max(2, menu.h // 5)
            icon_bounds = (
                slot_x0 + icon_margin_x,
                slot_y0 + icon_margin_y,
                slot_x1 - icon_margin_x,
                slot_y1 - icon_margin_y,
            )
            self._draw_item_icon(draw, item_label=item_label, bounds=icon_bounds, fill=icon_fill)
            cursor_x = slot_x1 + self._slot_gap + 1

        if start_index > 0:
            left_marker_x = x0 + 1
            center_y = (y0 + y1) // 2
            draw.polygon(
                (
                    (left_marker_x + 4, center_y - 3),
                    (left_marker_x + 1, center_y),
                    (left_marker_x + 4, center_y + 3),
                ),
                fill=0,
            )

        if start_index + visible_count < len(snapshot.items):
            right_marker_x = x1 - 1
            center_y = (y0 + y1) // 2
            draw.polygon(
                (
                    (right_marker_x - 4, center_y - 3),
                    (right_marker_x - 1, center_y),
                    (right_marker_x - 4, center_y + 3),
                ),
                fill=0,
            )

        if snapshot.notifications_count > 0:
            badge_radius = 2
            badge_cx = x1 - 5
            badge_cy = y0 + 5
            draw.ellipse(
                (
                    badge_cx - badge_radius,
                    badge_cy - badge_radius,
                    badge_cx + badge_radius,
                    badge_cy + badge_radius,
                ),
                fill=0,
            )

    def _compute_max_visible_slots(self, menu_width: int) -> int:
        usable_width = max(1, menu_width - 2 * self._horizontal_padding)
        return max(1, (usable_width + self._slot_gap) // (self._min_slot_width + self._slot_gap))

    @staticmethod
    def _resolve_window_start(item_count: int, selection_index: int, visible_count: int) -> int:
        if item_count <= visible_count:
            return 0
        start_index = max(0, selection_index - visible_count + 1)
        return min(start_index, item_count - visible_count)

    def _draw_item_icon(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        item_label: str,
        bounds: tuple[int, int, int, int],
        fill: int,
    ) -> None:
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            return

        normalized = item_label.strip().lower()
        state = ""
        if ":" in normalized:
            normalized, state = normalized.split(":", 1)
            normalized = normalized.strip()
            state = state.strip()

        if normalized.startswith("pet"):
            self._draw_pet_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("notify"):
            self._draw_notify_icon(draw, x0, y0, x1, y1, fill, state == "off")
            return
        if normalized.startswith("status"):
            self._draw_status_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("feed"):
            self._draw_feed_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("play"):
            self._draw_play_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("scratch"):
            self._draw_scratch_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("sleep"):
            self._draw_sleep_icon(draw, x0, y0, x1, y1, fill)
            return
        if normalized.startswith("wake"):
            self._draw_wake_icon(draw, x0, y0, x1, y1, fill)
            return

        draw.ellipse((x0 + 1, y0 + 1, x1 - 1, y1 - 1), outline=fill)

    @staticmethod
    def _draw_pet_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        head_y0 = y0 + 2
        head_y1 = y1 - 1
        draw.ellipse((x0 + 1, head_y0, x1 - 1, head_y1), outline=fill)
        draw.polygon(((x0 + 2, head_y0 + 1), (x0 + 5, y0), (x0 + 7, head_y0 + 2)), fill=fill)
        draw.polygon(((x1 - 2, head_y0 + 1), (x1 - 5, y0), (x1 - 7, head_y0 + 2)), fill=fill)
        eye_y = (head_y0 + head_y1) // 2
        draw.point((x0 + 4, eye_y), fill=fill)
        draw.point((x1 - 4, eye_y), fill=fill)

    @staticmethod
    def _draw_notify_icon(
        draw: ImageDraw.ImageDraw,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        fill: int,
        is_off: bool,
    ) -> None:
        bell_top = y0 + 1
        bell_bottom = y1 - 2
        draw.arc((x0 + 2, bell_top, x1 - 2, bell_bottom), start=185, end=355, fill=fill, width=1)
        draw.line((x0 + 2, bell_bottom, x1 - 2, bell_bottom), fill=fill, width=1)
        draw.ellipse((x0 + (x1 - x0) // 2 - 1, bell_bottom + 1, x0 + (x1 - x0) // 2 + 1, bell_bottom + 3), fill=fill)
        if is_off:
            draw.line((x0 + 1, y1 - 1, x1 - 1, y0 + 1), fill=fill, width=1)

    @staticmethod
    def _draw_status_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        mid_x = (x0 + x1) // 2
        draw.rectangle((x0 + 1, y1 - 3, x0 + 3, y1 - 1), fill=fill)
        draw.rectangle((mid_x - 1, y1 - 5, mid_x + 1, y1 - 1), fill=fill)
        draw.rectangle((x1 - 3, y1 - 7, x1 - 1, y1 - 1), fill=fill)

    @staticmethod
    def _draw_feed_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        rim_y = y0 + 3
        bowl_bottom = y1 - 2
        draw.line((x0 + 2, rim_y, x1 - 2, rim_y), fill=fill, width=1)
        draw.arc((x0 + 2, rim_y - 1, x1 - 2, bowl_bottom), start=10, end=170, fill=fill, width=1)

    @staticmethod
    def _draw_play_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        draw.polygon(((x0 + 2, y0 + 1), (x1 - 2, (y0 + y1) // 2), (x0 + 2, y1 - 1)), fill=fill)

    @staticmethod
    def _draw_scratch_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        draw.line((x0 + 1, y0 + 1, x1 - 1, y1 - 1), fill=fill, width=1)
        draw.line((x0 + 1, y1 - 1, x1 - 1, y0 + 1), fill=fill, width=1)
        draw.line((x0 + 1, (y0 + y1) // 2, x1 - 1, (y0 + y1) // 2), fill=fill, width=1)

    @staticmethod
    def _draw_sleep_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        draw.line((x0 + 1, y0 + 1, x1 - 1, y0 + 1), fill=fill, width=1)
        draw.line((x1 - 1, y0 + 1, x0 + 1, y1 - 1), fill=fill, width=1)
        draw.line((x0 + 1, y1 - 1, x1 - 1, y1 - 1), fill=fill, width=1)

    @staticmethod
    def _draw_wake_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill: int) -> None:
        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), outline=fill)
        draw.line((cx, y0 + 1, cx, cy - 3), fill=fill, width=1)
        draw.line((cx, cy + 3, cx, y1 - 1), fill=fill, width=1)
        draw.line((x0 + 1, cy, cx - 3, cy), fill=fill, width=1)
        draw.line((cx + 3, cy, x1 - 1, cy), fill=fill, width=1)


class ScreenRenderer:
    def __init__(
        self,
        layout_calculator: LayoutCalculator,
        menu_bar_renderer: MenuBarRenderer,
        pet_sprite_renderer: PetSpriteRenderer,
    ) -> None:
        self._layout_calculator = layout_calculator
        self._menu_bar_renderer = menu_bar_renderer
        self._pet_sprite_renderer = pet_sprite_renderer

    def render(
        self,
        *,
        framebuffer: FrameBuffer1Bit,
        capabilities: DisplayCapabilities,
        payload: RenderPayload,
        menu_controller: MenuController,
    ) -> bool:
        layout = self._layout_calculator.calculate(capabilities)
        canvas = Image.new("1", (capabilities.width, capabilities.height), color=1)

        # 1) Pet render clipped to content area.
        self._pet_sprite_renderer.render(
            canvas,
            theme_id=payload.theme_id,
            manifest=payload.manifest,
            animation_name=payload.animation_name,
            frame_index=payload.frame_index,
            content_rect=layout.content_rect,
        )

        # 2) Menu bar with icon-only entries.
        self._menu_bar_renderer.render(canvas, layout, menu_controller)

        # 3) Optional notifications overlay inside content viewport only.
        if menu_controller.notifications_overlay_enabled:
            self._render_notifications_overlay(canvas, layout, menu_controller)

        return framebuffer.replace_from_image(canvas)

    def _render_notifications_overlay(
        self,
        canvas: Image.Image,
        layout: ScreenLayout,
        menu_controller: MenuController,
    ) -> None:
        draw = ImageDraw.Draw(canvas)
        content = layout.content_rect
        notifications = menu_controller.get_notifications()[-5:]
        if not notifications:
            return

        panel_x0 = content.x + 4
        panel_y0 = content.y + 4
        panel_x1 = content.x + content.w - 4
        panel_y1 = min(content.y + content.h - 4, panel_y0 + 10 + 12 * len(notifications))

        draw.rectangle((panel_x0, panel_y0, panel_x1, panel_y1), fill=1, outline=0)
        text_y = panel_y0 + 3
        for message in notifications:
            draw.text((panel_x0 + 4, text_y), message[:26], fill=0)
            text_y += 12
