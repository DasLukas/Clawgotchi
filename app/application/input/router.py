from __future__ import annotations

from collections import deque
import threading

from app.domain.ui.input import InputEvent


class InputRouter:
    def __init__(self, max_queue_size: int = 256) -> None:
        self._lock = threading.Lock()
        self._queue: deque[InputEvent] = deque(maxlen=max_queue_size)

    def publish(self, event: InputEvent) -> None:
        with self._lock:
            self._queue.append(event)

    def drain(self, max_events: int) -> list[InputEvent]:
        if max_events <= 0:
            return []

        drained: list[InputEvent] = []
        with self._lock:
            for _ in range(min(max_events, len(self._queue))):
                drained.append(self._queue.popleft())

        return drained
