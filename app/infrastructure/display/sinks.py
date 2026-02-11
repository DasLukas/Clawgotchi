from __future__ import annotations

from app.application.ports.display import DisplayDriver, Frame
from core.framebuffer import FrameBuffer1Bit
from core.interfaces import DisplaySink


class DisplayDriverSink(DisplaySink):
    """Bridge legacy DisplayDriver implementations to the shared framebuffer pipeline."""

    def __init__(self, driver: DisplayDriver) -> None:
        self._driver = driver

    @property
    def driver(self) -> DisplayDriver:
        return self._driver

    def push(self, framebuffer: FrameBuffer1Bit) -> None:
        self._driver.render(Frame(image=framebuffer.to_pil_image()))
