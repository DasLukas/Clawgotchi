from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class PetCommand:
    type: str
    intensity: float = 1.0
    source: str = "api"
    command_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.type = self.type.strip().lower()
        if not self.type:
            raise ValueError("Command type must not be empty.")
        self.intensity = clamp(float(self.intensity), 0.0, 1.0)
        self.source = self.source.strip().lower() or "api"
