from __future__ import annotations

LEGACY_PLUGIN_ID_ALIASES: dict[str, str] = {
    "waveshare_2in7_display": "waveshare_epaper_27bw",
}

LEGACY_HARDWARE_PROFILE_ALIASES: dict[str, str] = {
    "waveshare_2in7": "waveshare_epaper_27bw",
}


def normalize_plugin_id(plugin_id: str, default: str = "") -> str:
    normalized = plugin_id.strip()
    if not normalized:
        normalized = default
    return LEGACY_PLUGIN_ID_ALIASES.get(normalized, normalized)


def normalize_hardware_profile_id(profile_id: str, default: str = "dummy") -> str:
    normalized = profile_id.strip()
    if not normalized:
        normalized = default
    return LEGACY_HARDWARE_PROFILE_ALIASES.get(normalized, normalized)
