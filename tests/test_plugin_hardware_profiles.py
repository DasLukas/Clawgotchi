from __future__ import annotations

import asyncio

from app.application.services import PluginService


class _DummyPluginRepository:
    def list_plugins(self) -> list[dict]:
        return [
            {
                "plugin_id": "waveshare_epaper_27bw",
                "manifest": {
                    "metadata": {
                        "hardware_profiles": [
                            {"id": "waveshare_epaper_27bw", "name": "Waveshare 2.7\" ePaper HAT"}
                        ]
                    }
                },
            }
        ]


def test_hardware_profiles_include_dummy_and_plugin_profiles() -> None:
    service = PluginService(
        plugin_loader=object(),
        plugin_repository=_DummyPluginRepository(),
        state_repository=object(),
        plugin_runtime=object(),
        settings_repository=object(),
    )

    profiles = service.list_hardware_profiles()

    assert profiles[0] == {"id": "dummy", "name": "Dummy/Mock display"}
    assert {"id": "waveshare_epaper_27bw", "name": "Waveshare 2.7\" ePaper HAT"} in profiles


class _State:
    def __init__(self) -> None:
        self.enabled_plugin_ids: list[str] = []
        self.hardware_profile = "dummy"


class _StateRepository:
    def __init__(self) -> None:
        self.state = _State()

    def load_or_create(self, pet_name: str):
        return self.state

    def save_state(self, state, source: str, command_id, events) -> int:
        return 1


class _SettingsRepository:
    def __init__(self) -> None:
        self.values = {"setup.pet_name": "Clawgotchi"}

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class _Runtime:
    async def activate(self, plugin_id: str) -> None:
        return None


class _PluginRepositoryForActivation:
    def __init__(self) -> None:
        self.plugins = [
            {
                "plugin_id": "waveshare_epaper_27bw",
                "enabled": False,
                "manifest": {
                    "metadata": {
                        "hardware_profiles": [
                            {"id": "waveshare_epaper_27bw", "name": "Waveshare 2.7\" ePaper HAT"}
                        ]
                    }
                },
            }
        ]

    def list_plugins(self) -> list[dict]:
        return self.plugins

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        for plugin in self.plugins:
            if plugin["plugin_id"] == plugin_id:
                plugin["enabled"] = enabled
                return
        raise ValueError(plugin_id)


def test_activate_hardware_profile_enables_provider_plugin() -> None:
    plugin_repository = _PluginRepositoryForActivation()
    state_repository = _StateRepository()
    settings_repository = _SettingsRepository()
    service = PluginService(
        plugin_loader=object(),
        plugin_repository=plugin_repository,
        state_repository=state_repository,
        plugin_runtime=_Runtime(),
        settings_repository=settings_repository,
    )

    asyncio.run(service.activate_hardware_profile("waveshare_epaper_27bw"))

    assert plugin_repository.list_plugins()[0]["enabled"] is True
    assert state_repository.state.hardware_profile == "waveshare_epaper_27bw"
