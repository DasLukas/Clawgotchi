from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.application.interfaces import PluginBase, PluginContext
from app.infrastructure.display.waveshare_epaper_2in7 import WaveshareEPaper2in7Driver


def _load_new_driver_type() -> type | None:
    module_name = "clawgotchi_plugin_waveshare_epaper_27bw_driver_legacy_alias"
    driver_path = (
        Path(__file__).resolve().parent.parent
        / "hardware"
        / "waveshare_epaper_27bw"
        / "driver.py"
    )
    if not driver_path.exists():
        return None

    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, driver_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return getattr(module, "WaveshareEPaper27BWDriver", None)


class Waveshare2in7LegacyDisplayPlugin(PluginBase):
    plugin_id = "waveshare_2in7_display"
    name = "Waveshare 2.7 Display Plugin (Legacy Alias)"

    async def on_startup(self, context: PluginContext) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    def get_hardware_drivers(self) -> list[str]:
        return ["waveshare_2in7"]

    def create_display_driver(self, profile_id: str, settings: Any) -> Any | None:
        if profile_id not in {"waveshare_2in7", "waveshare_epaper_27bw"}:
            return None

        new_driver_type = _load_new_driver_type()
        if new_driver_type is not None:
            return new_driver_type(settings=settings)

        return WaveshareEPaper2in7Driver(settings=settings)
