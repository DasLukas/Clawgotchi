from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "pet"):
            payload["pet"] = getattr(record, "pet")
        if hasattr(record, "emotion"):
            payload["emotion"] = getattr(record, "emotion")
        if hasattr(record, "theme"):
            payload["theme"] = getattr(record, "theme")
        if hasattr(record, "state_version"):
            payload["state_version"] = getattr(record, "state_version")
        if hasattr(record, "cue"):
            payload["cue"] = getattr(record, "cue")
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(JsonFormatter())
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
