from __future__ import annotations

from abc import ABC, abstractmethod

from core.framebuffer import FrameBuffer1Bit


class DisplaySink(ABC):
    """Consumes the shared framebuffer and forwards it to a concrete output target."""

    @abstractmethod
    def push(self, framebuffer: FrameBuffer1Bit) -> None:
        raise NotImplementedError


class NullDisplaySink(DisplaySink):
    def push(self, framebuffer: FrameBuffer1Bit) -> None:
        return None
