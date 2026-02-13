# Clawgotchi

Clawgotchi is an extensible FastAPI runtime with SQLite persistence, plugin/theme loading, a web UI, and Raspberry Pi hardware integration.

## Project Description

Clawgotchi runs as a local web service and virtual display mirror, with optional hardware display backends (for example Waveshare ePaper via plugin). The runtime is now user-directory based by default, so desktop installs on Linux/macOS/Windows do not need sudo/admin rights.

## Runtime Home (Permission-Safe Defaults)

By default, Clawgotchi stores writable state in a per-user runtime home:

- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi`
- macOS: `~/Library/Application Support/Clawgotchi`
- Windows: `%LOCALAPPDATA%\Clawgotchi`

Runtime layout:

- `db/clawgotchi.db`
- `logs/`
- `plugins/`
- `themes/`
- `cache/`
- `config/`
- `bin/`
- `.env`

Built-in repository plugins/themes remain available as read-only fallback roots. Runtime roots take precedence.

## Setup Instructions

### One-liner Install (macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install | bash
```

### One-liner Install (Windows PowerShell)

```powershell
irm https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install.ps1 | iex
```

### Unified One-liner (prints the correct platform command)

```bash
python -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/print_install_command.py').read())"
```

## Installation Steps (what bootstrap does)

Bootstrap installer flow (`scripts/install_bootstrap.sh` / `scripts/install_bootstrap.ps1` + `scripts/common_install.py`):

1. Verifies required tools (`git`, Python 3.11+).
2. Clones or updates source checkout (`~/.local/share/clawgotchi/src` on Unix-like systems, `%LOCALAPPDATA%\Clawgotchi\src` on Windows).
3. Creates/updates runtime virtualenv in runtime home (`venv`).
4. Installs dependencies into the virtualenv (`pip install -e <repo>`).
5. Creates runtime directories and runtime `.env` in runtime home.
6. Creates launchers:
   - Unix: runtime `bin/clawgotchi`, repo `./clawgotchi`, and `~/.local/bin/clawgotchi`
   - Windows: runtime `bin/clawgotchi.ps1` and repo `./clawgotchi.ps1`
7. Runs smoke diagnostics via doctor (`python -m clawgotchi.tools.doctor --smoke --check-startup`).

### Dry-run

Unix:

```bash
curl -fsSL https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/install_bootstrap.sh | bash -s -- --dry-run
```

Windows:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/install_bootstrap.ps1))) -DryRun
```

## Build / Run Instructions

After install:

- Unix: `clawgotchi`
- Windows: `& "$env:LOCALAPPDATA\Clawgotchi\bin\clawgotchi.ps1"`

Then open:

- `http://localhost:8000/`

## Reinstall / Update

The installer is idempotent. Re-run the same one-liner to update source + dependencies safely.

For repository-local updates, `update.sh` remains available and now supports runtime-venv resolution via `CLAW_VENV_PATH` / runtime home fallback.

## Raspberry Pi (Optional SPI/systemd path)

Desktop bootstrap does not install system services.

For Raspberry Pi SPI/systemd provisioning (opt-in only):

- Pass `--systemd` to bootstrap, or
- Run the legacy Pi installer explicitly:

```bash
sudo bash install.sh
```

This keeps Pi service/timer setup separate from desktop installs.

## Plugin Dependency Policy (Manager-Ready)

Plugin Python dependencies must install into the same Clawgotchi virtualenv (never global pip).

Helper command:

```bash
python -m clawgotchi.tools.plugin_deps install <plugin_id>
```

Behavior:

- Resolves plugin manifests from runtime + built-in roots.
- Installs declared plugin dependencies into the managed venv.
- Records installs in runtime registry: `plugins/registry.json`.

## Troubleshooting / Doctor

Run diagnostics:

```bash
python -m clawgotchi.tools.doctor --smoke --check-startup
```

Useful checks:

- `python -m clawgotchi.tools.doctor --json`
- `python -m clawgotchi.tools.display_test --backend dummy`
- `python -m clawgotchi.tools.display_test --backend waveshare_epaper_27bw`

## Development Workflow

### Local development setup

```bash
git clone https://github.com/DasLukas/Clawgotchi.git
cd Clawgotchi
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python main.py
```

### Tests

```bash
pytest
```

### Branch strategy

- `main`: publish/release branch
- `dev`: integration/development branch (if used in your workflow)

## Additional Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Design system: `docs/DESIGN.md`
- Theme authoring: `CONTRIBUTING.md`
