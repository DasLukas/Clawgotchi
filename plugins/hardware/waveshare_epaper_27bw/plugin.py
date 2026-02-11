from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.application.interfaces import PluginBase, PluginContext


def _load_driver_type():
    module_name = "clawgotchi_plugin_waveshare_epaper_27bw_driver"
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        path = Path(__file__).resolve().parent / "driver.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load display driver module from {path}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return getattr(module, "WaveshareEPaper27BWDriver")


class WaveshareEPaper27BWPlugin(PluginBase):
    plugin_id = "waveshare_epaper_27bw"
    name = "Waveshare 2.7 inch ePaper HAT (B/W)"

    async def on_startup(self, context: PluginContext) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    def get_hardware_drivers(self) -> list[str]:
        return ["waveshare_epaper_27bw"]

    def create_display_driver(self, profile_id: str, settings: Any) -> Any | None:
        if profile_id != "waveshare_epaper_27bw":
            return None
        driver_type = _load_driver_type()
        return driver_type(settings=settings)
