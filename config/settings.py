from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DisplaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAW_", env_file=".env", extra="ignore")

    display_type: str = "dummy"
    display_vendor: str = "waveshare"
    display_rotation: int = 0
    display_use_partial: bool = False
    display_dithering: bool = False
    display_debug_write_png: bool = True
    display_debug_png_path: str = "/tmp/clawgotchi_last_frame.png"

    @field_validator("display_rotation")
    @classmethod
    def validate_rotation(cls, value: int) -> int:
        if value not in {0, 90, 180, 270}:
            raise ValueError("Display rotation must be one of 0, 90, 180, or 270.")
        return value
