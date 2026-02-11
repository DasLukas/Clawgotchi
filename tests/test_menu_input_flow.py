from __future__ import annotations

from app.application.ui.menu_controller import MenuController
from app.domain.ui.input import ButtonId, InputEvent


def _event(button: ButtonId) -> InputEvent:
    return InputEvent(button=button, ts_ms=1)


def test_menu_navigation_wraps_with_next_and_back() -> None:
    controller = MenuController.create_default(action_dispatcher=lambda _: None)

    first_snapshot = controller.get_snapshot()
    assert first_snapshot.selection_index == 0

    controller.handle_event(_event(ButtonId.BACK))
    wrapped_snapshot = controller.get_snapshot()
    assert wrapped_snapshot.selection_index == len(wrapped_snapshot.items) - 1

    controller.handle_event(_event(ButtonId.NEXT))
    reset_snapshot = controller.get_snapshot()
    assert reset_snapshot.selection_index == 0


def test_special_toggles_overlay_at_root_and_jumps_to_root_from_submenu() -> None:
    controller = MenuController.create_default(action_dispatcher=lambda _: None)

    assert controller.notifications_overlay_enabled is False
    controller.handle_event(_event(ButtonId.SPECIAL))
    assert controller.notifications_overlay_enabled is True

    controller.handle_event(_event(ButtonId.CONFIRM))
    submenu_snapshot = controller.get_snapshot()
    assert submenu_snapshot.title == "Pet"

    controller.handle_event(_event(ButtonId.SPECIAL))
    root_snapshot = controller.get_snapshot()
    assert root_snapshot.title == "Menu"


def test_confirm_action_emits_pending_menu_action() -> None:
    controller = MenuController.create_default(action_dispatcher=lambda _: None)

    controller.handle_event(_event(ButtonId.CONFIRM))
    controller.handle_event(_event(ButtonId.CONFIRM))

    actions = controller.consume_pending_actions()
    assert "feed" in actions
