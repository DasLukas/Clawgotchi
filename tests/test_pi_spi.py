from __future__ import annotations

from pathlib import Path

from app.infrastructure.system.pi_spi import PiSpiManager, patch_spi_dtparam


def test_patch_spi_dtparam_is_idempotent_when_missing() -> None:
    original = "# Existing config\n"
    patched_once, changed_once = patch_spi_dtparam(original)
    patched_twice, changed_twice = patch_spi_dtparam(patched_once)

    assert changed_once is True
    assert "dtparam=spi=on" in patched_once
    assert changed_twice is False
    assert patched_twice == patched_once


def test_patch_spi_dtparam_rewrites_existing_spi_setting() -> None:
    original = "dtparam=spi=off\n"
    patched, changed = patch_spi_dtparam(original)

    assert changed is True
    assert patched == "dtparam=spi=on\n"


def test_spi_detection_uses_device_or_boot_config(tmp_path: Path) -> None:
    spidev = tmp_path / "dev" / "spidev0.0"
    config = tmp_path / "boot" / "config.txt"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("", encoding="utf-8")

    manager = PiSpiManager(spi_device_path=spidev, boot_config_paths=(config,))
    assert manager.is_spi_enabled() is False

    config.write_text("dtparam=spi=on\n", encoding="utf-8")
    assert manager.is_spi_enabled() is True

    config.write_text("", encoding="utf-8")
    spidev.parent.mkdir(parents=True, exist_ok=True)
    spidev.write_text("", encoding="utf-8")
    assert manager.is_spi_enabled() is True


def test_raspberry_pi_detection_from_model_text(tmp_path: Path, monkeypatch) -> None:
    manager = PiSpiManager(
        spi_device_path=tmp_path / "dev" / "spidev0.0",
        boot_config_paths=(tmp_path / "boot" / "config.txt",),
    )

    monkeypatch.setattr(manager, "_read_text", lambda path: "Raspberry Pi 4 Model B" if "model" in str(path) else "")
    assert manager.is_raspberry_pi() is True

    monkeypatch.setattr(manager, "_read_text", lambda path: "")
    assert manager.is_raspberry_pi() is False


def test_ensure_spi_ready_patches_boot_config_idempotently(tmp_path: Path, monkeypatch) -> None:
    spidev = tmp_path / "dev" / "spidev0.0"
    config = tmp_path / "boot" / "config.txt"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("# boot\n", encoding="utf-8")

    manager = PiSpiManager(spi_device_path=spidev, boot_config_paths=(config,))
    monkeypatch.setattr("app.infrastructure.system.pi_spi.os.geteuid", lambda: 1000)
    monkeypatch.setattr(manager, "is_raspberry_pi", lambda: True)
    monkeypatch.setattr(manager, "_enable_spi_via_raspi_config", lambda: False)
    monkeypatch.setattr(manager, "_write_privileged", lambda path, content: path.write_text(content, encoding="utf-8"))

    first = manager.ensure_spi_ready()
    second = manager.ensure_spi_ready()

    assert first.changed is True
    assert first.used_boot_config_patch is True
    assert second.changed is False
    assert config.read_text(encoding="utf-8").count("dtparam=spi=on") == 1
