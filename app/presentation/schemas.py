from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    type: str = Field(min_length=1)
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="api", min_length=1)


class CommandResponse(BaseModel):
    accepted: bool
    command_id: str
    state_version: int


class ImportStateRequest(BaseModel):
    snapshot: dict[str, Any]
    dry_run: bool = False


class ExportStateResponse(BaseModel):
    snapshot_id: str
    schema_version: int
    state_version: int
    created_at: str
    state: dict[str, Any]
