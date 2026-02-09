from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from app.domain.value_objects import PetCommand

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueuedCommand:
    command: PetCommand
    result_future: asyncio.Future[int]


class CommandQueueProtocol(Protocol):
    async def enqueue(self, command: PetCommand) -> asyncio.Future[int]:
        ...

    async def next_item(self) -> QueuedCommand:
        ...


class AsyncCommandQueue(CommandQueueProtocol):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()

    async def enqueue(self, command: PetCommand) -> asyncio.Future[int]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[int] = loop.create_future()
        await self._queue.put(QueuedCommand(command=command, result_future=future))
        return future

    async def next_item(self) -> QueuedCommand:
        return await self._queue.get()


class CommandHandlerProtocol(Protocol):
    async def handle(self, command: PetCommand) -> int:
        ...


class TickLoopProtocol(Protocol):
    async def run_tick(self) -> int:
        ...


class CommandWorker:
    def __init__(
        self,
        queue: CommandQueueProtocol,
        handler: CommandHandlerProtocol,
        stop_event: asyncio.Event,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._stop_event = stop_event

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                queued = await asyncio.wait_for(self._queue.next_item(), timeout=0.5)
            except TimeoutError:
                continue

            try:
                state_version = await self._handler.handle(queued.command)
                if not queued.result_future.done():
                    queued.result_future.set_result(state_version)
            except Exception as exc:
                logger.exception("Command processing failed.")
                if not queued.result_future.done():
                    queued.result_future.set_exception(exc)


class TickWorker:
    def __init__(self, service: TickLoopProtocol, interval_seconds: float, stop_event: asyncio.Event) -> None:
        self._service = service
        self._interval_seconds = max(0.5, interval_seconds)
        self._stop_event = stop_event

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                try:
                    await self._service.run_tick()
                except Exception:
                    logger.exception("Tick loop failed.")
