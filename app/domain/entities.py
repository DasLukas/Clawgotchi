from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.domain.events import DomainEvent
from app.domain.value_objects import PetCommand, clamp, utc_now


class Emotion(str, Enum):
    CONTENT = "content"
    HAPPY = "happy"
    EXCITED = "excited"
    SLEEPY = "sleepy"
    HUNGRY = "hungry"


@dataclass(slots=True)
class Needs:
    hunger: float = 25.0
    energy: float = 25.0
    social: float = 25.0
    cleanliness: float = 25.0

    def to_dict(self) -> dict[str, float]:
        return {
            "hunger": round(self.hunger, 2),
            "energy": round(self.energy, 2),
            "social": round(self.social, 2),
            "cleanliness": round(self.cleanliness, 2),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Needs":
        return cls(
            hunger=float(payload.get("hunger", 25.0)),
            energy=float(payload.get("energy", 25.0)),
            social=float(payload.get("social", 25.0)),
            cleanliness=float(payload.get("cleanliness", 25.0)),
        )


@dataclass(slots=True)
class Pet:
    pet_id: str
    name: str
    emotion: Emotion = Emotion.CONTENT
    needs: Needs = field(default_factory=Needs)
    sleeping: bool = False
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, name: str) -> "Pet":
        normalized_name = name.strip() or "Clawgotchi"
        return cls(pet_id=str(uuid4()), name=normalized_name)

    def apply_tick(self) -> list[DomainEvent]:
        delta = 1.5
        self.needs.hunger = clamp(self.needs.hunger + delta, 0.0, 100.0)
        self.needs.social = clamp(self.needs.social + delta, 0.0, 100.0)
        self.needs.cleanliness = clamp(self.needs.cleanliness + 1.0, 0.0, 100.0)

        if self.sleeping:
            self.needs.energy = clamp(self.needs.energy - 2.0, 0.0, 100.0)
        else:
            self.needs.energy = clamp(self.needs.energy + delta, 0.0, 100.0)

        self._refresh_emotion()
        self.updated_at = utc_now()
        return [DomainEvent(event_type="tick_processed", payload={"pet_id": self.pet_id})]

    def apply_command(self, command: PetCommand) -> list[DomainEvent]:
        events: list[DomainEvent] = [
            DomainEvent(
                event_type="command_received",
                payload={
                    "command_id": command.command_id,
                    "type": command.type,
                    "source": command.source,
                },
            )
        ]

        intensity_scale = 5.0 + (20.0 * command.intensity)

        if command.type == "feed":
            self.needs.hunger = clamp(self.needs.hunger - intensity_scale, 0.0, 100.0)
            self.emotion = Emotion.HAPPY
            events.append(DomainEvent(event_type="pet_fed", payload={"intensity": command.intensity}))
        elif command.type == "play":
            self.needs.social = clamp(self.needs.social - intensity_scale, 0.0, 100.0)
            self.needs.energy = clamp(self.needs.energy + 3.0, 0.0, 100.0)
            self.emotion = Emotion.EXCITED
            events.append(DomainEvent(event_type="pet_played", payload={"intensity": command.intensity}))
        elif command.type == "sleep":
            self.sleeping = True
            self.emotion = Emotion.SLEEPY
            events.append(DomainEvent(event_type="pet_sleeping", payload={}))
        elif command.type == "wake":
            self.sleeping = False
            self.emotion = Emotion.CONTENT
            events.append(DomainEvent(event_type="pet_awake", payload={}))
        elif command.type == "scratch":
            self.needs.social = clamp(self.needs.social - (intensity_scale / 2), 0.0, 100.0)
            self.emotion = Emotion.HAPPY
            events.append(DomainEvent(event_type="pet_scratched", payload={"intensity": command.intensity}))
        elif command.type == "status":
            events.append(DomainEvent(event_type="status_requested", payload={}))
        else:
            events.append(
                DomainEvent(
                    event_type="command_forwarded_to_plugins",
                    payload={"type": command.type},
                )
            )

        self._refresh_emotion()
        self.updated_at = utc_now()
        return events

    def _refresh_emotion(self) -> None:
        stress = (self.needs.hunger + self.needs.energy + self.needs.social) / 3.0
        if self.sleeping:
            self.emotion = Emotion.SLEEPY
        elif stress >= 70.0:
            self.emotion = Emotion.HUNGRY
        elif stress >= 45.0:
            self.emotion = Emotion.CONTENT
        elif stress >= 20.0:
            self.emotion = Emotion.HAPPY
        else:
            self.emotion = Emotion.EXCITED

    def to_dict(self) -> dict[str, Any]:
        return {
            "pet_id": self.pet_id,
            "name": self.name,
            "emotion": self.emotion.value,
            "needs": self.needs.to_dict(),
            "sleeping": self.sleeping,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Pet":
        emotion_value = str(payload.get("emotion", Emotion.CONTENT.value))
        try:
            emotion = Emotion(emotion_value)
        except ValueError:
            emotion = Emotion.CONTENT

        updated = payload.get("updated_at")
        updated_at = datetime.fromisoformat(updated) if isinstance(updated, str) else utc_now()

        return cls(
            pet_id=str(payload.get("pet_id") or str(uuid4())),
            name=str(payload.get("name") or "Clawgotchi"),
            emotion=emotion,
            needs=Needs.from_dict(payload.get("needs", {})),
            sleeping=bool(payload.get("sleeping", False)),
            updated_at=updated_at,
        )


@dataclass(slots=True)
class DeviceState:
    pet: Pet
    schema_version: int = 1
    state_version: int = 0
    active_theme_id: str = "classic"
    enabled_plugin_ids: list[str] = field(default_factory=list)
    hardware_profile: str = "dummy"
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, pet_name: str) -> "DeviceState":
        return cls(pet=Pet.create(pet_name))

    def apply_tick(self) -> list[DomainEvent]:
        events = self.pet.apply_tick()
        self.bump_version()
        return events

    def apply_command(self, command: PetCommand) -> list[DomainEvent]:
        events = self.pet.apply_command(command)
        self.bump_version()
        return events

    def bump_version(self) -> None:
        self.state_version += 1
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "active_theme_id": self.active_theme_id,
            "enabled_plugin_ids": list(self.enabled_plugin_ids),
            "hardware_profile": self.hardware_profile,
            "updated_at": self.updated_at.isoformat(),
            "pet": self.pet.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeviceState":
        updated = payload.get("updated_at")
        updated_at = datetime.fromisoformat(updated) if isinstance(updated, str) else utc_now()
        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            state_version=int(payload.get("state_version", 0)),
            active_theme_id=str(payload.get("active_theme_id", "classic")),
            enabled_plugin_ids=list(payload.get("enabled_plugin_ids", [])),
            hardware_profile=str(payload.get("hardware_profile", "dummy")),
            updated_at=updated_at,
            pet=Pet.from_dict(payload.get("pet", {})),
        )
