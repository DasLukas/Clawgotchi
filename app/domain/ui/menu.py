from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class MenuItem:
    item_id: str
    label: str


@dataclass(slots=True)
class ActionItem(MenuItem):
    action_id: str


@dataclass(slots=True)
class ToggleItem(MenuItem):
    getter: Callable[[], bool]
    setter: Callable[[bool], None]


@dataclass(slots=True)
class SubMenuItem(MenuItem):
    children: list[MenuItem] = field(default_factory=list)


MenuEntry = ActionItem | ToggleItem | SubMenuItem
