from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


@dataclass(slots=True)
class PetState:
    name: str
    emotion: str
    current_animation: str = "idle"
    animation_until_ts: float | None = None
    animation_frame_index: int = 0
    animation_started_ts: float | None = None
    last_render_ts: float | None = None

    @classmethod
    def create(cls, name: str, emotion: str) -> "PetState":
        now_ts = time()
        return cls(
            name=name,
            emotion=emotion,
            current_animation="idle",
            animation_until_ts=None,
            animation_frame_index=0,
            animation_started_ts=now_ts,
            last_render_ts=None,
        )

    def sync_identity(self, name: str, emotion: str) -> None:
        self.name = name
        self.emotion = emotion

    def set_temporary_animation(self, animation: str, duration_ms: int, now_ts: float | None = None) -> None:
        effective_now = now_ts if now_ts is not None else time()
        duration_seconds = max(0.0, duration_ms / 1000.0)
        self.current_animation = animation
        self.animation_started_ts = effective_now
        self.animation_until_ts = effective_now + duration_seconds
        self.animation_frame_index = 0

    def ensure_idle_if_expired(self, now_ts: float) -> bool:
        if self.animation_until_ts is None:
            if self.current_animation != "idle":
                self.current_animation = "idle"
                self.animation_started_ts = now_ts
                self.animation_frame_index = 0
                return True
            return False

        if now_ts < self.animation_until_ts:
            return False

        self.current_animation = "idle"
        self.animation_until_ts = None
        self.animation_started_ts = now_ts
        self.animation_frame_index = 0
        return True

    def mark_rendered(self, now_ts: float, frame_index: int) -> None:
        self.last_render_ts = now_ts
        self.animation_frame_index = frame_index

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "emotion": self.emotion,
            "current_animation": self.current_animation,
            "animation_until_ts": self.animation_until_ts,
            "animation_frame_index": self.animation_frame_index,
            "animation_started_ts": self.animation_started_ts,
            "last_render_ts": self.last_render_ts,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], fallback_name: str, fallback_emotion: str) -> "PetState":
        return cls(
            name=str(payload.get("name", fallback_name)),
            emotion=str(payload.get("emotion", fallback_emotion)),
            current_animation=str(payload.get("current_animation", "idle")),
            animation_until_ts=(
                float(payload["animation_until_ts"])
                if payload.get("animation_until_ts") is not None
                else None
            ),
            animation_frame_index=int(payload.get("animation_frame_index", 0)),
            animation_started_ts=(
                float(payload["animation_started_ts"])
                if payload.get("animation_started_ts") is not None
                else None
            ),
            last_render_ts=(
                float(payload["last_render_ts"])
                if payload.get("last_render_ts") is not None
                else None
            ),
        )
