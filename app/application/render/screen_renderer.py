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


class MenuSidebarRenderer:
    def __init__(self, sidebar_padding: int = 4) -> None:
        self._padding = max(1, sidebar_padding)

    def render(self, canvas: Image.Image, layout: ScreenLayout, menu_controller: MenuController) -> None:
        draw = ImageDraw.Draw(canvas)
        sidebar_w = layout.sidebar_width
        height = canvas.height

        draw.rectangle((0, 0, sidebar_w - 1, height - 1), fill=1)
        draw.line((sidebar_w - 1, 0, sidebar_w - 1, height - 1), fill=0, width=1)

        snapshot = menu_controller.get_snapshot()
        draw.text((self._padding, self._padding), snapshot.title[:8], fill=0)

        y = self._padding + 14
        line_height = 12
        max_rows = max(1, (height - y - 30) // line_height)

        start_index = 0
        if snapshot.selection_index >= max_rows:
            start_index = snapshot.selection_index - max_rows + 1

        visible_items = snapshot.items[start_index : start_index + max_rows]

        for idx, item_label in enumerate(visible_items):
            absolute_idx = start_index + idx
            row_top = y + idx * line_height
            selected = absolute_idx == snapshot.selection_index

            if selected:
                draw.rectangle((1, row_top - 1, sidebar_w - 3, row_top + line_height - 2), fill=0)
                draw.text((self._padding, row_top), item_label[:9], fill=1)
            else:
                draw.text((self._padding, row_top), item_label[:9], fill=0)

        indicator_y = height - 26
        for indicator in snapshot.indicators[:2]:
            draw.text((self._padding, indicator_y), indicator[:9], fill=0)
            indicator_y += 10

        if snapshot.notifications_count > 0:
            badge_text = f"N:{snapshot.notifications_count}"
            draw.text((self._padding, height - 12), badge_text[:9], fill=0)


class ScreenRenderer:
    def __init__(
        self,
        layout_calculator: LayoutCalculator,
        menu_sidebar_renderer: MenuSidebarRenderer,
        pet_sprite_renderer: PetSpriteRenderer,
    ) -> None:
        self._layout_calculator = layout_calculator
        self._menu_sidebar_renderer = menu_sidebar_renderer
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

        # 1) Sidebar first (always visible)
        self._menu_sidebar_renderer.render(canvas, layout, menu_controller)

        # 2) Pet render clipped to content area only
        self._pet_sprite_renderer.render(
            canvas,
            theme_id=payload.theme_id,
            manifest=payload.manifest,
            animation_name=payload.animation_name,
            frame_index=payload.frame_index,
            content_rect=layout.content_rect,
        )

        # 3) Optional notifications overlay inside content viewport only
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
