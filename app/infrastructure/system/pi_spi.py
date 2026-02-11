from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

logger = logging.getLogger(__name__)

DEFAULT_SPI_DEVICE_PATH = Path("/dev/spidev0.0")
DEFAULT_BOOT_CONFIG_PATHS = (Path("/boot/config.txt"), Path("/boot/firmware/config.txt"))
DEFAULT_SUDOERS_PATH = Path("/etc/sudoers.d/clawgotchi-hw")

SUDOERS_SNIPPET = (
    "clawgotchi ALL=(root) NOPASSWD: "
    "/usr/bin/raspi-config nonint do_spi 0, "
    "/usr/bin/tee /boot/config.txt, "
    "/usr/bin/tee /boot/firmware/config.txt\n"
)

ONE_TIME_ADMIN_INSTRUCTIONS = """Run these one-time admin commands exactly:

sudo tee /etc/sudoers.d/clawgotchi-hw >/dev/null <<'EOF'
clawgotchi ALL=(root) NOPASSWD: /usr/bin/raspi-config nonint do_spi 0, /usr/bin/tee /boot/config.txt, /usr/bin/tee /boot/firmware/config.txt
EOF
sudo chmod 0440 /etc/sudoers.d/clawgotchi-hw
"""

SPI_ON_PATTERN = re.compile(r"^\s*dtparam=spi=on(?:\s*#.*)?\s*$", re.IGNORECASE)
SPI_ANY_PATTERN = re.compile(r"^\s*dtparam=spi=.*$", re.IGNORECASE)


class PrivilegeRequiredError(RuntimeError):
    pass


@dataclass(slots=True)
class SpiSetupResult:
    running_on_raspberry_pi: bool
    spi_enabled: bool
    changed: bool
    used_raspi_config: bool
    used_boot_config_patch: bool
    reboot_required: bool
    notes: list[str] = field(default_factory=list)


def patch_spi_dtparam(content: str) -> tuple[str, bool]:
    lines = content.splitlines()

    for line in lines:
        if SPI_ON_PATTERN.match(line):
            return content, False

    for index, line in enumerate(lines):
        if SPI_ANY_PATTERN.match(line):
            lines[index] = "dtparam=spi=on"
            return "\n".join(lines) + "\n", True

    if lines and lines[-1].strip():
        lines.append("")
    if not any(item.strip() == "# Added by Clawgotchi SPI helper" for item in lines):
        lines.append("# Added by Clawgotchi SPI helper")
    lines.append("dtparam=spi=on")
    return "\n".join(lines) + "\n", True


class PiSpiManager:
    def __init__(
        self,
        spi_device_path: Path = DEFAULT_SPI_DEVICE_PATH,
        boot_config_paths: tuple[Path, ...] = DEFAULT_BOOT_CONFIG_PATHS,
        sudoers_path: Path = DEFAULT_SUDOERS_PATH,
    ) -> None:
        self._spi_device_path = spi_device_path
        self._boot_config_paths = boot_config_paths
        self._sudoers_path = sudoers_path

    def is_raspberry_pi(self) -> bool:
        model_candidates = (
            Path("/proc/device-tree/model"),
            Path("/sys/firmware/devicetree/base/model"),
        )
        for path in model_candidates:
            value = self._read_text(path)
            if "Raspberry Pi" in value:
                return True

        cpuinfo = self._read_text(Path("/proc/cpuinfo"))
        return "Raspberry Pi" in cpuinfo or "BCM2" in cpuinfo or "BCM27" in cpuinfo

    def is_spi_enabled(self) -> bool:
        if self._spi_device_path.exists():
            return True
        return any(self._config_has_spi_enabled(path) for path in self._boot_config_paths)

    def ensure_spi_ready(self, app_user: str = "clawgotchi") -> SpiSetupResult:
        running_on_pi = self.is_raspberry_pi()
        result = SpiSetupResult(
            running_on_raspberry_pi=running_on_pi,
            spi_enabled=False,
            changed=False,
            used_raspi_config=False,
            used_boot_config_patch=False,
            reboot_required=False,
        )

        logger.info(
            "Checking Raspberry Pi SPI state.",
            extra={
                "running_on_pi": running_on_pi,
                "spi_device_path": str(self._spi_device_path),
            },
        )

        if not running_on_pi:
            result.notes.append("Not running on Raspberry Pi hardware.")
            result.spi_enabled = False
            return result

        if os.geteuid() == 0:
            self.ensure_sudoers_policy(user=app_user)

        if self._spi_device_path.exists():
            result.spi_enabled = True
            result.notes.append(f"SPI device already present at {self._spi_device_path}.")
            return result

        if any(self._config_has_spi_enabled(path) for path in self._boot_config_paths):
            result.spi_enabled = True
            result.reboot_required = True
            result.notes.append("SPI is configured in boot config but /dev/spidev0.0 is not present yet.")
            return result

        if self._enable_spi_via_raspi_config():
            result.changed = True
            result.used_raspi_config = True
            if self._spi_device_path.exists():
                result.spi_enabled = True
                result.notes.append("SPI enabled via raspi-config.")
                return result
            result.reboot_required = True
            result.notes.append("raspi-config completed. A reboot may be required for /dev/spidev0.0.")

        patched = self._ensure_boot_config_spi_enabled()
        if patched:
            result.changed = True
            result.used_boot_config_patch = True
            result.reboot_required = True
            result.notes.append("Updated boot configuration with dtparam=spi=on.")

        result.spi_enabled = self._spi_device_path.exists() or any(
            self._config_has_spi_enabled(path) for path in self._boot_config_paths
        )
        if not result.spi_enabled:
            result.notes.append("SPI could not be enabled automatically.")
        return result

    def ensure_sudoers_policy(self, user: str = "clawgotchi") -> bool:
        if os.geteuid() != 0:
            return False

        content = SUDOERS_SNIPPET.replace("clawgotchi", user)
        current = self._read_text(self._sudoers_path)
        if current == content:
            return False

        self._sudoers_path.parent.mkdir(parents=True, exist_ok=True)
        self._sudoers_path.write_text(content, encoding="utf-8")
        self._sudoers_path.chmod(stat.S_IRUSR | stat.S_IRGRP)
        logger.info("Updated hardware sudoers policy.", extra={"path": str(self._sudoers_path), "user": user})
        return True

    def _enable_spi_via_raspi_config(self) -> bool:
        raspi_config = shutil.which("raspi-config")
        if raspi_config is None:
            logger.info("raspi-config is not installed; fallback to boot config patching.")
            return False

        command = [raspi_config, "nonint", "do_spi", "0"]
        completed = self._run_privileged(command)
        if completed.returncode == 0:
            logger.info("SPI enabled through raspi-config.")
            return True

        logger.warning(
            "raspi-config failed to enable SPI.",
            extra={"returncode": completed.returncode, "stderr": completed.stderr.strip()},
        )
        return False

    def _ensure_boot_config_spi_enabled(self) -> bool:
        changed = False
        existing_paths = [path for path in self._boot_config_paths if path.exists()]
        target_paths = existing_paths
        if not target_paths and self._boot_config_paths:
            primary = self._boot_config_paths[0]
            if primary.parent.exists():
                target_paths = [primary]

        for path in target_paths:
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            patched, file_changed = patch_spi_dtparam(original)
            if not file_changed:
                continue
            self._write_privileged(path, patched)
            changed = True
            logger.info("Patched boot config to enable SPI.", extra={"path": str(path)})
        return changed

    def _config_has_spi_enabled(self, path: Path) -> bool:
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        return any(SPI_ON_PATTERN.match(line) for line in content.splitlines())

    def _run_privileged(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if os.geteuid() == 0:
            return subprocess.run(command, capture_output=True, text=True, check=False)

        sudo_path = shutil.which("sudo")
        if sudo_path is None:
            raise PrivilegeRequiredError(ONE_TIME_ADMIN_INSTRUCTIONS)

        completed = subprocess.run([sudo_path, "-n", *command], capture_output=True, text=True, check=False)
        if completed.returncode != 0 and _is_sudo_auth_error(completed.stderr):
            raise PrivilegeRequiredError(ONE_TIME_ADMIN_INSTRUCTIONS)
        return completed

    def _write_privileged(self, path: Path, content: str) -> None:
        if os.geteuid() == 0:
            path.write_text(content, encoding="utf-8")
            return

        sudo_path = shutil.which("sudo")
        tee_path = shutil.which("tee")
        if sudo_path is None or tee_path is None:
            raise PrivilegeRequiredError(ONE_TIME_ADMIN_INSTRUCTIONS)

        completed = subprocess.run(
            [sudo_path, "-n", tee_path, str(path)],
            input=content,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 and _is_sudo_auth_error(completed.stderr):
            raise PrivilegeRequiredError(ONE_TIME_ADMIN_INSTRUCTIONS)
        if completed.returncode != 0:
            raise RuntimeError(f"Failed to patch {path}: {completed.stderr.strip()}")

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip("\x00")
        except FileNotFoundError:
            return ""
        except OSError:
            return ""
def _is_sudo_auth_error(stderr: str) -> bool:
    normalized = stderr.lower()
    indicators = (
        "password is required",
        "a password is required",
        "not in the sudoers file",
        "is not allowed to execute",
        "may not run sudo",
    )
    return any(indicator in normalized for indicator in indicators)
