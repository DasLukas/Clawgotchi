from __future__ import annotations

import argparse
import importlib.util
import logging
from pathlib import Path
import sys
import time
from typing import Any

from PIL import Image, ImageDraw

from app.application.ports.display import Frame
from app.infrastructure.display.dummy import DummyDisplayDriver
from config.settings import DisplaySettings

logger = logging.getLogger(__name__)


def _load_waveshare_driver_type():
    project_root = Path(__file__).resolve().parents[2]
    driver_path = project_root / "plugins" / "hardware" / "waveshare_epaper_27bw" / "driver.py"
    if not driver_path.exists():
        raise FileNotFoundError(f"Waveshare plugin driver file was not found: {driver_path}")

    module_name = "clawgotchi_tools_waveshare_driver"
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, driver_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load plugin driver module from {driver_path}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return getattr(module, "WaveshareEPaper27BWDriver")


def _build_driver(args: argparse.Namespace):
    settings = DisplaySettings(
        display_rotation=args.rotation,
        display_use_partial=args.partial,
        display_spi_bus=args.spi_bus,
        display_spi_device=args.spi_device,
        display_spi_max_hz=args.spi_max_hz,
        display_gpio_dc_pin=args.dc_pin,
        display_gpio_rst_pin=args.rst_pin,
        display_gpio_busy_pin=args.busy_pin,
        display_gpio_cs_pin=args.cs_pin,
    )

    if args.backend == "dummy":
        return DummyDisplayDriver(rotation=args.rotation, write_debug_png=False)

    if args.backend == "waveshare_epaper_27bw":
        driver_type = _load_waveshare_driver_type()
        return driver_type(settings=settings)

    raise ValueError(f"Unsupported backend: {args.backend}")


def _draw_frame(index: int, width: int, height: int) -> Image.Image:
    image = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=0, width=2)
    draw.text((12, 12), "Clawgotchi ready", fill=0)
    draw.text((12, 36), f"Display test frame {index}", fill=0)
    draw.text((12, 60), time.strftime("%Y-%m-%d %H:%M:%S"), fill=0)
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render test frames on a selected display backend.")
    parser.add_argument("--backend", default="dummy", choices=["dummy", "waveshare_epaper_27bw"])
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--spi-max-hz", type=int, default=2_000_000)
    parser.add_argument("--dc-pin", type=int, default=25)
    parser.add_argument("--rst-pin", type=int, default=17)
    parser.add_argument("--busy-pin", type=int, default=24)
    parser.add_argument("--cs-pin", type=int, default=8)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logger.info("Starting display test.", extra={"backend": args.backend, "frames": args.frames})

    driver = _build_driver(args)
    driver.init()
    capabilities = driver.get_capabilities()

    for frame_index in range(1, args.frames + 1):
        frame = _draw_frame(frame_index, capabilities.width, capabilities.height)
        driver.render(Frame(image=frame))
        time.sleep(max(args.sleep_seconds, 0.0))

    driver.sleep()
    logger.info("Display test completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
