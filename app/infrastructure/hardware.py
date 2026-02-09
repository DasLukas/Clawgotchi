from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class DummyInputDriver:
    async def read(self) -> dict[str, str]:
        await asyncio.sleep(0)
        return {"event": "none"}


class DummyAudioDriver:
    async def play(self, cue: str) -> None:
        await asyncio.sleep(0)
        logger.info("Dummy audio cue", extra={"cue": cue})


class DummySensorDriver:
    async def sample(self) -> dict[str, float]:
        await asyncio.sleep(0)
        return {"temperature": 0.0, "humidity": 0.0}
