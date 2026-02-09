from __future__ import annotations

from typing import Any

from app.application.interfaces import PluginBase, PluginContext
from app.infrastructure.display.waveshare_epaper_2in7 import WaveshareEPaper2in7Driver


class Waveshare2in7DisplayPlugin(PluginBase):
    plugin_id = "waveshare_2in7_display"
    name = "Waveshare 2.7 Display Plugin"

    async def on_startup(self, context: PluginContext) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    def get_hardware_drivers(self) -> list[str]:
        return ["waveshare_2in7"]

    def create_display_driver(self, profile_id: str, settings: Any) -> WaveshareEPaper2in7Driver | None:
        if profile_id != "waveshare_2in7":
            return None
        return WaveshareEPaper2in7Driver(settings=settings)
