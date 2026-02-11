from __future__ import annotations

import logging
import time
from typing import Any

from app.application.input.router import InputRouter
from app.domain.ui.input import ButtonId, InputEvent

logger = logging.getLogger(__name__)


class GPIOButtonDriver:
    def __init__(
        self,
        router: InputRouter,
        pin_mapping: dict[ButtonId, int],
        debounce_ms: int = 120,
    ) -> None:
        self._router = router
        self._pin_mapping = dict(pin_mapping)
        self._debounce_ms = max(0, int(debounce_ms))
        self._buttons: list[Any] = []
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        try:
            from gpiozero import Button  # type: ignore
        except Exception:
            logger.info("GPIO button driver disabled because gpiozero is unavailable.")
            self._enabled = False
            return

        created_any = False

        for button_id, pin in self._pin_mapping.items():
            if pin is None or int(pin) < 0:
                continue

            try:
                button = Button(pin=int(pin), bounce_time=(self._debounce_ms / 1000.0) if self._debounce_ms else None)
                button.when_pressed = self._build_press_callback(button_id)
                self._buttons.append(button)
                created_any = True
            except Exception:
                logger.exception("Failed to initialize GPIO button.", extra={"button": button_id.value, "pin": pin})

        self._enabled = created_any
        if self._enabled:
            logger.info(
                "GPIO button driver started.",
                extra={"pins": {button.value: pin for button, pin in self._pin_mapping.items()}},
            )
        else:
            logger.info("GPIO button driver has no active pins and remains disabled.")

    def stop(self) -> None:
        for button in self._buttons:
            try:
                button.close()
            except Exception:
                logger.debug("Failed to close GPIO button cleanly.", exc_info=True)

        self._buttons = []
        self._enabled = False

    def _build_press_callback(self, button_id: ButtonId):
        def callback() -> None:
            self._router.publish(
                InputEvent(
                    button=button_id,
                    ts_ms=int(time.time() * 1000),
                )
            )

        return callback
