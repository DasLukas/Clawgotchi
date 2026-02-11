from __future__ import annotations

from app.application.hardware_aliases import normalize_hardware_profile_id, normalize_plugin_id


def test_normalize_legacy_plugin_id() -> None:
    assert normalize_plugin_id("waveshare_2in7_display") == "waveshare_epaper_27bw"


def test_normalize_legacy_hardware_profile() -> None:
    assert normalize_hardware_profile_id("waveshare_2in7") == "waveshare_epaper_27bw"


def test_normalize_defaults() -> None:
    assert normalize_plugin_id("", default="dummy_plugin") == "dummy_plugin"
    assert normalize_hardware_profile_id("", default="dummy") == "dummy"
