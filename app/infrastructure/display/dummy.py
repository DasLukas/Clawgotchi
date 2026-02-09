from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from app.application.ports.display import DisplayCapabilities, DisplayDriver, Frame

logger = logging.getLogger(__name__)


class DummyDisplayDriver(DisplayDriver):
    def __init__(
        self,
        width: int = 264,
        height: int = 176,
        rotation: int = 0,
        write_debug_png: bool = True,
        debug_png_path: str = "/tmp/clawgotchi_last_frame.png",
    ) -> None:
        self._capabilities = DisplayCapabilities(
            width=width,
            height=height,
            color_mode="1bit",
            rotation=rotation,
            supports_partial_update=False,
            typical_refresh_ms=1200,
        )
        self._write_debug_png = write_debug_png
        self._debug_png_path = Path(debug_png_path)
        self._last_frame: Image.Image | None = None
        self._initialized = False
        self._asleep = False

    def init(self) -> None:
        self._initialized = True
        self._asleep = False

    def sleep(self) -> None:
        self._asleep = True

    def wake(self) -> None:
        if not self._initialized:
            self.init()
        self._asleep = False

    def get_capabilities(self) -> DisplayCapabilities:
        return self._capabilities

    def render(self, frame: Frame) -> None:
        if not self._initialized:
            self.init()
        if self._asleep:
            self.wake()

        image = frame.image
        if not isinstance(image, Image.Image):
            raise TypeError("DummyDisplayDriver expects Frame.image to be a PIL Image.")

        image_to_store = image.convert("1", dither=Image.NONE)
        self._last_frame = image_to_store.copy()

        if self._write_debug_png:
            self._debug_png_path.parent.mkdir(parents=True, exist_ok=True)
            self._last_frame.save(self._debug_png_path, format="PNG")

        logger.debug("Dummy display rendered frame", extra={"path": str(self._debug_png_path)})

    def get_last_frame(self) -> Image.Image | None:
        if self._last_frame is None:
            return None
        return self._last_frame.copy()
