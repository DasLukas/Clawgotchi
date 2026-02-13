from __future__ import annotations

import argparse
import logging
import time

from PIL import Image, ImageDraw

from app.application.ports.display import Frame
from app.infrastructure.display.dummy import DummyDisplayDriver

logger = logging.getLogger(__name__)


def _build_driver(args: argparse.Namespace) -> DummyDisplayDriver:
    return DummyDisplayDriver(rotation=args.rotation, write_debug_png=False)


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
    parser.add_argument("--backend", default="dummy", choices=["dummy"])
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
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
