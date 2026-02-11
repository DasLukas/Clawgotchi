from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.display import DisplayCapabilities


@dataclass(slots=True)
class LayoutConfig:
    sidebar_ratio: float = 0.18
    sidebar_min_width: int = 40
    sidebar_max_width: int = 72


@dataclass(slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class ScreenLayout:
    sidebar_width: int
    content_rect: Rect


class LayoutCalculator:
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self._config = config or LayoutConfig()

    def calculate(self, capabilities: DisplayCapabilities) -> ScreenLayout:
        width = max(1, int(capabilities.width))
        height = max(1, int(capabilities.height))

        raw_sidebar = round(width * self._config.sidebar_ratio)
        sidebar_width = max(self._config.sidebar_min_width, min(self._config.sidebar_max_width, raw_sidebar))
        sidebar_width = min(sidebar_width, max(1, width - 1))

        content_rect = Rect(x=sidebar_width, y=0, w=width - sidebar_width, h=height)
        return ScreenLayout(sidebar_width=sidebar_width, content_rect=content_rect)
