# Clawgotchi

Clawgotchi is an extensible FastAPI runtime with SQLite persistence, plugin/theme loading, a web UI, and plugin-based hardware integration.

## Project Description

Clawgotchi runs as a local web service with a virtual display mirror. Hardware drivers are provided by plugins, with the built-in `dummy` backend as the safe default.

## Runtime Home (Permission-Safe Defaults)

By default, Clawgotchi stores writable runtime state in a per-user directory:

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

The app uses these paths by default, so repository folders stay read-only unless you change configuration.

## Setup Instructions

Prerequisites:

- Python `>= 3.11`
- Git

Recommended repository location (best practice):

- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi/src`
- macOS: `~/Library/Application Support/Clawgotchi/src`
- Windows: `%LOCALAPPDATA%\Clawgotchi\src`

You can still clone the repository to any other user-writable path.

## Installation Steps

### macOS / Linux

```bash
git clone https://github.com/DasLukas/Clawgotchi.git
cd Clawgotchi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows (PowerShell)

```powershell
git clone https://github.com/DasLukas/Clawgotchi.git
cd Clawgotchi
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Build / Run Instructions

From repository root with the virtual environment active:

```bash
python main.py
```

Open:

- `http://127.0.0.1:8000/`

## Manual Update Workflow

Automatic install/update scripts were removed. Update manually with Git.

### Update your local instance

```bash
git pull --ff-only
python -m pip install -e ".[dev]"
```

If you prefer release-only dependencies:

```bash
python -m pip install -e .
```

## Development Workflow

### Local development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python main.py
```

### Tests

```bash
python -m pytest -q
```

### Branch strategy

- `main`: publish/release branch
- `dev`: development/integration branch (optional, depending on team workflow)

## Plugin Dependency Policy

Plugin Python dependencies must install into the same project virtual environment (never global pip).

Helper command:

```bash
python -m clawgotchi.tools.plugin_deps install <plugin_id>
```

## Troubleshooting / Doctor

```bash
python -m clawgotchi.tools.doctor --smoke --check-startup
python -m clawgotchi.tools.doctor --json
python -m clawgotchi.tools.display_test --backend dummy
```

## Additional Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Design system: `docs/DESIGN.md`
- Theme authoring: `CONTRIBUTING.md`
