from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.domain.value_objects import utc_now


@dataclass(slots=True)
class StateSnapshot:
    schema_version: int
    state_version: int
    state: dict[str, Any]
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "created_at": self.created_at.isoformat(),
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StateSnapshot":
        created_raw = payload.get("created_at")
        created_at = datetime.fromisoformat(created_raw) if isinstance(created_raw, str) else utc_now()
        return cls(
            snapshot_id=str(payload.get("snapshot_id") or str(uuid4())),
            schema_version=int(payload.get("schema_version", 1)),
            state_version=int(payload.get("state_version", 0)),
            created_at=created_at,
            state=dict(payload.get("state") or {}),
        )
