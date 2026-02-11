from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class DisplayCapabilities:
    width: int
    height: int
    color_mode: Literal["1bit"]
    rotation: Literal[0, 90, 180, 270]
    supports_partial_update: bool
    typical_refresh_ms: int


@dataclass(slots=True)
class Frame:
    image: Any


class DisplayDriver(ABC):
    @abstractmethod
    def init(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def sleep(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def wake(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> DisplayCapabilities:
        raise NotImplementedError

    @abstractmethod
    def render(self, frame: Frame) -> None:
        raise NotImplementedError
