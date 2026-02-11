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
    display_spi_bus: int = 0
    display_spi_device: int = 0
    display_spi_max_hz: int = 2_000_000
    display_gpio_dc_pin: int = 25
    display_gpio_rst_pin: int = 17
    display_gpio_busy_pin: int = 24
    display_gpio_cs_pin: int = 8

    @field_validator("display_rotation")
    @classmethod
    def validate_rotation(cls, value: int) -> int:
        if value not in {0, 90, 180, 270}:
            raise ValueError("Display rotation must be one of 0, 90, 180, or 270.")
        return value

    @field_validator(
        "display_spi_bus",
        "display_spi_device",
        "display_spi_max_hz",
        "display_gpio_dc_pin",
        "display_gpio_rst_pin",
        "display_gpio_busy_pin",
        "display_gpio_cs_pin",
    )
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Display SPI and GPIO settings must be non-negative integers.")
        return value
