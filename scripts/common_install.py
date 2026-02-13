#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shlex
import stat
import subprocess
import sys
from typing import Sequence


DEFAULT_REPO_URL = "https://github.com/DasLukas/Clawgotchi.git"


class InstallError(RuntimeError):
    """Raised when bootstrap installation cannot proceed safely."""


def log(message: str) -> None:
    """Print a structured installer log line."""

    print(f"[clawgotchi-install] {message}")


def get_runtime_home() -> Path:
    """Resolve per-user runtime home path for the active OS.

    Resolution order:
    1. `CLAW_RUNTIME_HOME`
    2. Platform default application data directory

    Returns:
        Absolute runtime home path.
    """

    explicit_home = os.environ.get("CLAW_RUNTIME_HOME")
    if explicit_home:
        return Path(explicit_home).expanduser()

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser() / "Clawgotchi"
        return Path.home() / "AppData" / "Local" / "Clawgotchi"

    if platform.system().lower() == "darwin":
        return Path.home() / "Library" / "Application Support" / "Clawgotchi"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base_directory = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return base_directory / "clawgotchi"


def get_runtime_layout(runtime_home: Path) -> dict[str, Path]:
    """Build canonical runtime directories and file paths."""

    home = runtime_home.expanduser()
    return {
        "runtime_home": home,
        "db_directory": home / "db",
        "database_path": home / "db" / "clawgotchi.db",
        "logs_directory": home / "logs",
        "plugin_directory": home / "plugins",
        "theme_directory": home / "themes",
        "cache_directory": home / "cache",
        "config_directory": home / "config",
        "bin_directory": home / "bin",
        "env_file": home / ".env",
        "plugin_registry_file": home / "plugins" / "registry.json",
    }


def ensure_directories(layout: dict[str, Path], dry_run: bool = False) -> None:
    """Create runtime directories with user-scoped permissions.

    Parameters:
        layout: Runtime layout mapping.
        dry_run: When true, print operations without executing them.
    """

    directory_keys = {
        "runtime_home",
        "db_directory",
        "logs_directory",
        "plugin_directory",
        "theme_directory",
        "cache_directory",
        "config_directory",
        "bin_directory",
    }
    for key in directory_keys:
        path = layout[key]
        if dry_run:
            log(f"DRY-RUN mkdir -p {path}")
            continue
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                path.chmod(0o700)
            except OSError:
                pass


def sqlite_url_for_path(database_path: Path) -> str:
    """Build SQLAlchemy SQLite URL for an absolute filesystem path."""

    resolved = database_path.expanduser().resolve()
    return f"sqlite:///{resolved.as_posix()}"


def run_command(command: Sequence[str], dry_run: bool = False, cwd: Path | None = None) -> None:
    """Execute a subprocess command with optional dry-run logging.

    Parameters:
        command: Command and arguments.
        dry_run: When true, print command without executing.
        cwd: Optional working directory.

    Raises:
        InstallError: If command execution fails.
    """

    command_str = shlex.join(str(part) for part in command)
    if cwd is not None:
        command_str = f"(cd {shlex.quote(str(cwd))} && {command_str})"
    if dry_run:
        log(f"DRY-RUN {command_str}")
        return

    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or f"exit={completed.returncode}"
        raise InstallError(f"Command failed: {command_str}\n{details}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def _venv_python_path(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def write_runtime_env_file(
    env_file: Path,
    runtime_home: Path,
    repo_root: Path,
    layout: dict[str, Path],
    dry_run: bool = False,
) -> None:
    """Write runtime `.env` defaults in user-writable runtime home.

    Parameters:
        env_file: Target env file path.
        runtime_home: Runtime home path.
        repo_root: Repository source checkout path.
        layout: Runtime layout mapping.
        dry_run: When true, print changes without writing.
    """

    runtime_plugins = layout["plugin_directory"].resolve()
    runtime_themes = layout["theme_directory"].resolve()
    repo_plugins = (repo_root / "plugins").resolve()
    repo_themes = (repo_root / "themes").resolve()
    database_url = sqlite_url_for_path(layout["database_path"])
    config_file = (repo_root / "config" / "defaults.toml").resolve()
    debug_png = (layout["cache_directory"] / "clawgotchi_last_frame.png").resolve()

    env_lines = [
        "# Clawgotchi runtime environment (managed by installer)",
        f"CLAW_RUNTIME_HOME={runtime_home.resolve()}",
        f"CLAW_DATABASE_URL={database_url}",
        f"CLAW_PLUGIN_DIRECTORY={runtime_plugins}",
        f"CLAW_THEME_DIRECTORY={runtime_themes}",
        f"CLAW_PLUGIN_DIRECTORIES={runtime_plugins},{repo_plugins}",
        f"CLAW_THEME_DIRECTORIES={runtime_themes},{repo_themes}",
        f"CLAW_CONFIG_FILE={config_file}",
        f"CLAW_DISPLAY_DEBUG_PNG_PATH={debug_png}",
    ]
    payload = "\n".join(env_lines) + "\n"

    if dry_run:
        log(f"DRY-RUN write {env_file}")
        return

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(payload, encoding="utf-8")
    if os.name != "nt":
        try:
            env_file.chmod(0o600)
        except OSError:
            pass


def _build_unix_launcher_script(runtime_home: Path, env_file: Path, venv_python: Path, repo_root: Path) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -Eeuo pipefail",
            f'export CLAW_RUNTIME_HOME="{runtime_home.resolve()}"',
            f'export CLAW_ENV_FILE="{env_file.resolve()}"',
            f'export CLAW_VENV_PATH="{venv_python.resolve().parent.parent}"',
            "export PYTHONUNBUFFERED=1",
            f'exec "{venv_python.resolve()}" "{(repo_root / "main.py").resolve()}" "$@"',
            "",
        ]
    )


def _build_windows_launcher_script(runtime_home: Path, env_file: Path, venv_python: Path, repo_root: Path) -> str:
    return "\n".join(
        [
            '$ErrorActionPreference = "Stop"',
            f'$env:CLAW_RUNTIME_HOME = "{runtime_home.resolve()}"',
            f'$env:CLAW_ENV_FILE = "{env_file.resolve()}"',
            f'$env:CLAW_VENV_PATH = "{venv_python.resolve().parent.parent}"',
            '$env:PYTHONUNBUFFERED = "1"',
            f'& "{venv_python.resolve()}" "{(repo_root / "main.py").resolve()}" @Args',
            "",
        ]
    )


def write_launcher(path: Path, payload: str, dry_run: bool = False) -> None:
    """Write a launcher script at target path.

    Parameters:
        path: Launcher script output path.
        payload: Launcher script content.
        dry_run: When true, print action without writing.
    """

    if dry_run:
        log(f"DRY-RUN write launcher {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    if os.name != "nt":
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def create_launchers(
    runtime_home: Path,
    repo_root: Path,
    venv_python: Path,
    env_file: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Create platform launchers in runtime home, repo root, and user bin.

    Parameters:
        runtime_home: Runtime home path.
        repo_root: Source checkout path.
        venv_python: Virtual environment Python executable.
        env_file: Runtime env file path.
        dry_run: When true, print actions without writing.

    Returns:
        List of created launcher paths.
    """

    launchers: list[Path] = []
    runtime_bin = runtime_home / "bin"

    if os.name == "nt":
        launcher_payload = _build_windows_launcher_script(runtime_home, env_file, venv_python, repo_root)
        runtime_launcher = runtime_bin / "clawgotchi.ps1"
        repo_launcher = repo_root / "clawgotchi.ps1"
        write_launcher(runtime_launcher, launcher_payload, dry_run=dry_run)
        write_launcher(repo_launcher, launcher_payload, dry_run=dry_run)
        launchers.extend([runtime_launcher, repo_launcher])
        return launchers

    launcher_payload = _build_unix_launcher_script(runtime_home, env_file, venv_python, repo_root)
    runtime_launcher = runtime_bin / "clawgotchi"
    repo_launcher = repo_root / "clawgotchi"
    write_launcher(runtime_launcher, launcher_payload, dry_run=dry_run)
    write_launcher(repo_launcher, launcher_payload, dry_run=dry_run)
    launchers.extend([runtime_launcher, repo_launcher])

    xdg_bin_home = Path(os.environ.get("XDG_BIN_HOME", str(Path.home() / ".local" / "bin"))).expanduser()
    path_launcher = xdg_bin_home / "clawgotchi"
    write_launcher(path_launcher, launcher_payload, dry_run=dry_run)
    launchers.append(path_launcher)
    return launchers


def run_smoke_test(venv_python: Path, dry_run: bool = False) -> None:
    """Run doctor smoke tests after dependency installation.

    Parameters:
        venv_python: Virtual environment Python executable.
        dry_run: When true, print planned test command.
    """

    run_command(
        [
            str(venv_python),
            "-m",
            "clawgotchi.tools.doctor",
            "--smoke",
            "--check-startup",
            "--timeout-seconds",
            "20",
        ],
        dry_run=dry_run,
    )


def create_or_update_venv(venv_path: Path, repo_root: Path, dry_run: bool = False) -> Path:
    """Create/update virtual environment and install project dependencies.

    Parameters:
        venv_path: Target virtual environment directory.
        repo_root: Source checkout path.
        dry_run: When true, print planned commands.

    Returns:
        Python executable path inside the managed virtual environment.
    """

    venv_python = _venv_python_path(venv_path)
    if not venv_python.exists():
        run_command([sys.executable, "-m", "venv", str(venv_path)], dry_run=dry_run)

    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"], dry_run=dry_run)
    run_command([str(venv_python), "-m", "pip", "install", "-e", str(repo_root)], dry_run=dry_run)
    return venv_python


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse installer CLI arguments."""

    parser = argparse.ArgumentParser(description="Common cross-platform installer logic for Clawgotchi.")
    parser.add_argument("--repo-root", required=True, help="Absolute path to local source checkout.")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Repository URL used for user output.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing the system.")
    parser.add_argument(
        "--systemd",
        action="store_true",
        help="Request optional Raspberry Pi systemd/SPI guidance after desktop bootstrap.",
    )
    parser.add_argument("--skip-smoke", action="store_true", help="Skip doctor smoke test execution.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run shared bootstrap installation workflow.

    Parameters:
        argv: Optional argument vector.

    Returns:
        Exit code (`0` on success, non-zero on failure).

    Usage example:
        `python scripts/common_install.py --repo-root ~/.local/share/clawgotchi/src`
    """

    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.exists():
        raise InstallError(f"Repository path does not exist: {repo_root}")
    if not (repo_root / "main.py").exists():
        raise InstallError(f"Repository root does not contain main.py: {repo_root}")

    runtime_home = get_runtime_home()
    layout = get_runtime_layout(runtime_home)
    ensure_directories(layout, dry_run=args.dry_run)

    venv_path = runtime_home / "venv"
    venv_python = create_or_update_venv(venv_path=venv_path, repo_root=repo_root, dry_run=args.dry_run)

    write_runtime_env_file(
        env_file=layout["env_file"],
        runtime_home=runtime_home,
        repo_root=repo_root,
        layout=layout,
        dry_run=args.dry_run,
    )
    launchers = create_launchers(
        runtime_home=runtime_home,
        repo_root=repo_root,
        venv_python=venv_python,
        env_file=layout["env_file"],
        dry_run=args.dry_run,
    )

    if not args.skip_smoke:
        run_smoke_test(venv_python=venv_python, dry_run=args.dry_run)

    log("Installation finished.")
    log(f"Source checkout: {repo_root}")
    log(f"Runtime home: {runtime_home.resolve()}")
    for launcher in launchers:
        log(f"Launcher: {launcher}")

    if os.name == "nt":
        log(f"Run now: & \"{(runtime_home / 'bin' / 'clawgotchi.ps1').resolve()}\"")
        log("Optional: add %LOCALAPPDATA%\\Clawgotchi\\bin to PATH for direct 'clawgotchi.ps1' usage.")
    else:
        log("Run now: clawgotchi")
        log(
            "If command is not found, add ~/.local/bin to PATH: "
            "export PATH=\"$HOME/.local/bin:$PATH\""
        )

    if args.systemd:
        log(
            "Optional Raspberry Pi systemd/SPI provisioning is not enabled automatically. "
            "Run the legacy installer manually when required: sudo bash install.sh"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print(f"[clawgotchi-install] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
