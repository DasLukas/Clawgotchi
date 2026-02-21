from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.display import DisplayCapabilities


@dataclass(slots=True)
class LayoutConfig:
    menu_bar_ratio: float = 0.22
    menu_bar_min_height: int = 28
    menu_bar_max_height: int = 48


@dataclass(slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class ScreenLayout:
    menu_bar_height: int
    content_rect: Rect
    menu_rect: Rect


class LayoutCalculator:
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self._config = config or LayoutConfig()

    def calculate(self, capabilities: DisplayCapabilities) -> ScreenLayout:
        width = max(1, int(capabilities.width))
        height = max(1, int(capabilities.height))

        raw_menu_bar = round(height * self._config.menu_bar_ratio)
        menu_bar_height = max(
            self._config.menu_bar_min_height,
            min(self._config.menu_bar_max_height, raw_menu_bar),
        )
        menu_bar_height = min(menu_bar_height, max(1, height - 1))

        content_height = max(1, height - menu_bar_height)
        content_rect = Rect(x=0, y=0, w=width, h=content_height)
        menu_rect = Rect(x=0, y=content_height, w=width, h=height - content_height)
        return ScreenLayout(menu_bar_height=menu_bar_height, content_rect=content_rect, menu_rect=menu_rect)
