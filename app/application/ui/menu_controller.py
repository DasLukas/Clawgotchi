from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.domain.ui.input import ButtonId, InputEvent
from app.domain.ui.menu import ActionItem, MenuEntry, SubMenuItem, ToggleItem


IndicatorProvider = Callable[[], list[str]]


@dataclass(slots=True)
class MenuSnapshot:
    title: str
    items: list[str]
    selection_index: int
    notifications_count: int
    notifications_overlay_enabled: bool
    indicators: list[str]


class MenuController:
    def __init__(
        self,
        root_menu: SubMenuItem,
        indicator_provider: IndicatorProvider | None = None,
        notifications_limit: int = 10,
    ) -> None:
        self._root_menu = root_menu
        self._indicator_provider = indicator_provider or (lambda: [])
        self._notifications_limit = max(1, notifications_limit)

        self._stack: list[SubMenuItem] = [self._root_menu]
        self._selection_stack: list[int] = [0]
        self._notifications_overlay_enabled = False
        self._notifications: list[str] = []
        self._pending_actions: list[str] = []

    @classmethod
    def create_default(
        cls,
        action_dispatcher: Callable[[str], None],
        indicator_provider: IndicatorProvider | None = None,
    ) -> "MenuController":
        notifications_enabled = {"value": False}

        def get_notifications_enabled() -> bool:
            return notifications_enabled["value"]

        def set_notifications_enabled(value: bool) -> None:
            notifications_enabled["value"] = value

        root = SubMenuItem(
            item_id="root",
            label="Menu",
            children=[
                SubMenuItem(
                    item_id="pet_actions",
                    label="Pet",
                    children=[
                        ActionItem(item_id="feed", label="Feed", action_id="feed"),
                        ActionItem(item_id="play", label="Play", action_id="play"),
                        ActionItem(item_id="scratch", label="Scratch", action_id="scratch"),
                        ActionItem(item_id="sleep", label="Sleep", action_id="sleep"),
                        ActionItem(item_id="wake", label="Wake", action_id="wake"),
                    ],
                ),
                ToggleItem(
                    item_id="notify_overlay",
                    label="Notify",
                    getter=get_notifications_enabled,
                    setter=set_notifications_enabled,
                ),
                ActionItem(item_id="status", label="Status", action_id="status"),
            ],
        )

        controller = cls(root_menu=root, indicator_provider=indicator_provider)
        controller.set_action_dispatcher(action_dispatcher)
        return controller

    def set_action_dispatcher(self, action_dispatcher: Callable[[str], None]) -> None:
        self._action_dispatcher = action_dispatcher

    @property
    def notifications_overlay_enabled(self) -> bool:
        return self._notifications_overlay_enabled

    def consume_pending_actions(self) -> list[str]:
        pending = list(self._pending_actions)
        self._pending_actions.clear()
        return pending

    def register_root_item(self, item: MenuEntry) -> None:
        self._root_menu.children.append(item)

    def get_notifications(self) -> list[str]:
        return list(self._notifications)

    def get_snapshot(self) -> MenuSnapshot:
        items = self._current_items()
        labels = [self._format_item_label(item) for item in items]
        return MenuSnapshot(
            title=self._stack[-1].label,
            items=labels,
            selection_index=self._selection_stack[-1] if labels else 0,
            notifications_count=len(self._notifications),
            notifications_overlay_enabled=self._notifications_overlay_enabled,
            indicators=self._indicator_provider(),
        )

    def handle_event(self, event: InputEvent) -> bool:
        items = self._current_items()
        if not items and event.button != ButtonId.SPECIAL:
            return False

        changed = False

        if event.button == ButtonId.NEXT:
            changed = self._move_selection(delta=1)
        elif event.button == ButtonId.BACK:
            changed = self._move_selection(delta=-1)
        elif event.button == ButtonId.CONFIRM:
            changed = self._confirm_selection()
        elif event.button == ButtonId.SPECIAL:
            if len(self._stack) > 1:
                self._stack = [self._root_menu]
                self._selection_stack = [0]
                self._append_notification("Returned to root menu")
            else:
                self._notifications_overlay_enabled = not self._notifications_overlay_enabled
                state = "enabled" if self._notifications_overlay_enabled else "disabled"
                self._append_notification(f"Notifications overlay {state}")
            changed = True

        return changed

    def _move_selection(self, delta: int) -> bool:
        items = self._current_items()
        if not items:
            return False

        current = self._selection_stack[-1]
        next_index = (current + delta) % len(items)
        if next_index == current:
            return False

        self._selection_stack[-1] = next_index
        return True

    def _confirm_selection(self) -> bool:
        items = self._current_items()
        if not items:
            return False

        selected = items[self._selection_stack[-1]]

        if isinstance(selected, ActionItem):
            self._pending_actions.append(selected.action_id)
            self._append_notification(f"Action: {selected.label}")
            if hasattr(self, "_action_dispatcher"):
                self._action_dispatcher(selected.action_id)
            return True

        if isinstance(selected, ToggleItem):
            current = bool(selected.getter())
            selected.setter(not current)
            state = "on" if not current else "off"
            self._append_notification(f"{selected.label}: {state}")
            return True

        if isinstance(selected, SubMenuItem):
            self._stack.append(selected)
            self._selection_stack.append(0)
            return True

        return False

    def _current_items(self) -> list[MenuEntry]:
        return list(self._stack[-1].children)

    def _format_item_label(self, item: MenuEntry) -> str:
        if isinstance(item, ToggleItem):
            suffix = "ON" if item.getter() else "OFF"
            return f"{item.label}:{suffix}"
        return item.label

    def _append_notification(self, message: str) -> None:
        self._notifications.append(message)
        if len(self._notifications) > self._notifications_limit:
            self._notifications = self._notifications[-self._notifications_limit :]
