from __future__ import annotations

from app.application.interfaces import PluginBase, PluginContext
from app.domain.entities import DeviceState
from app.domain.events import DomainEvent
from app.domain.value_objects import PetCommand, clamp


class ExampleFunPlugin(PluginBase):
    plugin_id = "example_fun"
    name = "Example Fun Plugin"

    async def on_startup(self, context: PluginContext) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    async def on_tick(self, state: DeviceState) -> list[DomainEvent]:
        if state.pet.needs.social > 80.0:
            return [
                DomainEvent(
                    event_type="example_fun_lonely_hint",
                    payload={"message": "Try command: wave"},
                )
            ]
        return []

    async def on_command(self, state: DeviceState, command: PetCommand) -> list[DomainEvent]:
        if command.type != "wave":
            return []

        state.pet.needs.social = clamp(state.pet.needs.social - (15.0 * command.intensity), 0.0, 100.0)
        state.pet.needs.energy = clamp(state.pet.needs.energy + 1.0, 0.0, 100.0)

        return [
            DomainEvent(
                event_type="example_fun_wave_performed",
                payload={
                    "plugin_id": self.plugin_id,
                    "intensity": command.intensity,
                },
            )
        ]

    def get_commands(self) -> list[str]:
        return ["wave"]

    def get_emotions(self) -> list[str]:
        return ["playful"]

    def get_mini_games(self) -> list[str]:
        return ["guess-the-claw"]

    def get_hardware_drivers(self) -> list[str]:
        return ["example-servo-v1"]

    def get_ui_extensions(self) -> list[str]:
        return ["fun-panel"]
