from __future__ import annotations

from app.application.services import PluginService


class _DummyPluginRepository:
    def list_plugins(self) -> list[dict]:
        return [
            {
                "plugin_id": "waveshare_2in7_display",
                "manifest": {
                    "metadata": {
                        "hardware_profiles": [
                            {"id": "waveshare_2in7", "name": "Waveshare 2.7 inch ePaper"}
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

    assert profiles[0] == {"id": "dummy", "name": "Dummy (No Hardware)"}
    assert {"id": "waveshare_2in7", "name": "Waveshare 2.7 inch ePaper"} in profiles
