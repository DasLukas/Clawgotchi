# Clawgotchi

Clawgotchi is an extensible FastAPI runtime with SQLite persistence, plugin/theme loading, a web UI, and plugin-based hardware integration.

## Project Description

Clawgotchi runs as a local web service and virtual display mirror, with optional plugin-based hardware display backends. The runtime is now user-directory based by default, so desktop installs on Linux/macOS/Windows do not need sudo/admin rights.

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

## Program Workspace (Best-Practice Host Location)

The installer creates and maintains a dedicated per-user workspace for the application:

- macOS: `~/Library/Application Support/Clawgotchi`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi`
- Windows: `%LOCALAPPDATA%\Clawgotchi`

Source checkout location:

- macOS: `~/Library/Application Support/Clawgotchi/src`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi/src`
- Windows: `%LOCALAPPDATA%\Clawgotchi\src`

## Setup Instructions

### Install on macOS

```bash
curl -fsSL https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install | bash
```

### Install on Linux (desktop/server without systemd service)

```bash
curl -fsSL https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install | bash
```

### Install on Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install.ps1 | iex
```

### Unified One-liner (prints the correct platform command)

```bash
python -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/print_install_command.py').read())"
```

### Install from an already cloned local repository

```bash
cd /path/to/Clawgotchi
bash ./install
```

This command still installs into the dedicated workspace (`.../Clawgotchi/src`) and does not run from your current development folder.

## Installation Steps (what bootstrap does)

Bootstrap installer flow (`scripts/install_bootstrap.sh` / `scripts/install_bootstrap.ps1` + `scripts/common_install.py`):

1. Verifies required tools (`git`, Python 3.11+).
2. Clones or updates source checkout in the platform workspace (`~/Library/Application Support/Clawgotchi/src`, `${XDG_DATA_HOME:-~/.local/share}/clawgotchi/src`, `%LOCALAPPDATA%\Clawgotchi\src`).
3. If the managed source checkout is broken/non-git, it is moved to a timestamped backup directory and re-cloned cleanly.
4. Creates/updates runtime virtualenv in runtime home (`venv`).
5. Installs dependencies into the virtualenv (`pip install -e <repo>`).
6. Creates runtime directories and runtime `.env` in runtime home.
7. Creates launchers:
   - Unix: runtime `bin/clawgotchi`, repo `./clawgotchi.sh`, and `~/.local/bin/clawgotchi`
   - Windows: runtime `bin/clawgotchi.ps1` and repo `./clawgotchi.ps1`
8. Runs smoke diagnostics via doctor (`python -m clawgotchi.tools.doctor --smoke --check-startup`).

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

## Update Workflow (Simplified Git Handling)

The installer is idempotent. Re-run the same one-liner to update source + dependencies safely.

`update.sh` now defaults to **managed workspace update mode**:

- refreshes virtualenv tooling
- reinstalls the managed checkout (`pip install -e <runtime_home>/src`)
- delegates automatically to the managed workspace when launched from another clone
- does **not** run `git fetch/pull` unless explicitly requested
- does **not** force a pip self-upgrade unless explicitly requested
- retries once with virtualenv recreation if editable install fails (permission/tooling self-heal)

This avoids update failures caused by local branch state, dirty working trees, or incomplete fetch objects.

### Update on macOS/Linux desktop installs

Recommended:

```bash
curl -fsSL https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install | bash
```

If you are in another local checkout, `./update.sh` delegates to the managed workspace automatically.

If you explicitly want to update the current development checkout:

```bash
cd /path/to/Clawgotchi
./update.sh --local-repo
```

If you explicitly want a git pull in managed mode:

```bash
./update.sh --sync-git
```

Managed mode is default to keep application updates separated from development repositories.

If you also want to upgrade pip during update:

```bash
./update.sh --sync-git --upgrade-pip
```

### Update on Windows installs

```powershell
irm https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/install.ps1 | iex
```

### Update on Raspberry Pi service/timer installs

The generated systemd update helper runs `update.sh` in git-sync mode (`CLWG_SYNC_GIT=1`) with local-checkout pinning (`CLWG_FORCE_LOCAL_REPO=1`) so nightly updates continue to pull from `origin/main` on the Pi checkout.

## Linux Service Integration (Optional systemd path)

Desktop bootstrap does not install system services.

For optional systemd provisioning (opt-in only):

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

If update reports Python compatibility issues (`requires >=3.11`), force a compatible bootstrap interpreter:

```bash
CLAW_BOOTSTRAP_PYTHON=/opt/homebrew/bin/python3.12 "$HOME/Library/Application Support/Clawgotchi/src/update.sh"
```

## Development Workflow

### Local development setup

```bash
git clone https://github.com/DasLukas/Clawgotchi.git
cd Clawgotchi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python main.py
```

### Tests

```bash
python -m pytest -q
```

### Branch strategy

- `main`: publish/release branch
- `dev`: integration/development branch (if used in your workflow)

## Additional Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Design system: `docs/DESIGN.md`
- Theme authoring: `CONTRIBUTING.md`
