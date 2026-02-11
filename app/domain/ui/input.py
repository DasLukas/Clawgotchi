from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ButtonId(str, Enum):
    NEXT = "NEXT"
    BACK = "BACK"
    CONFIRM = "CONFIRM"
    SPECIAL = "SPECIAL"


@dataclass(slots=True)
class InputEvent:
    button: ButtonId
    ts_ms: int
