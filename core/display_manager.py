from __future__ import annotations

from collections.abc import Callable
import logging
import threading

from core.framebuffer import FrameBuffer1Bit
from core.interfaces import DisplaySink

logger = logging.getLogger(__name__)


FrameUpdateListener = Callable[[int, int], None]


class DisplayManager:
    """Coordinates all display sinks and fan-out updates from the shared framebuffer."""

    def __init__(self, sinks: list[DisplaySink] | None = None) -> None:
        self._lock = threading.RLock()
        self._sinks: list[DisplaySink] = list(sinks or [])
        self._listeners: list[FrameUpdateListener] = []

    def set_sinks(self, sinks: list[DisplaySink]) -> None:
        with self._lock:
            self._sinks = list(sinks)

    def add_sink(self, sink: DisplaySink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def subscribe(self, listener: FrameUpdateListener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return unsubscribe

    def push(self, framebuffer: FrameBuffer1Bit) -> None:
        with self._lock:
            sinks = tuple(self._sinks)
            listeners = tuple(self._listeners)

        for sink in sinks:
            try:
                sink.push(framebuffer)
            except Exception:
                logger.exception("Display sink push failed.", extra={"sink": type(sink).__name__})

        version = framebuffer.version
        updated_at_ms = framebuffer.updated_at_ms

        for listener in listeners:
            try:
                listener(version, updated_at_ms)
            except Exception:
                logger.exception("Display update listener failed.")
