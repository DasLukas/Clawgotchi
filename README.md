# Clawgotchi

Extensible app skeleton for a Raspberry Pi based Clawgotchi (Tamagotchi-like pet rendered on ePaper).

## Features

- Layered architecture: `domain`, `application`, `infrastructure`, `presentation`
- OOP-first design with explicit service/use-case classes
- FastAPI REST API + Jinja2 server-rendered web interface
- Setup wizard and dashboard
- Filesystem plugin system with web-managed enable/disable and rescan
- Filesystem theme system with web-managed activation and rescan
- SQLite persistence with versioned state snapshots and import/export
- Async command queue worker and async tick loop worker
- Dummy hardware drivers for display/input/audio/sensors

## Tech stack

- Python 3.11+
- FastAPI + Uvicorn
- Jinja2 templates
- SQLAlchemy + SQLite
- pydantic-settings

## Repository structure

```
.
├── app/
│   ├── application/
│   ├── domain/
│   ├── infrastructure/
│   └── presentation/
├── config/
├── plugins/
├── themes/
├── tests/
├── main.py
└── README.md
```

## Git Branch Workflow

### `main`

- Publish/release branch
- Stable, tested, runnable releases only
- No direct feature development
- Every merge to `main` is a release and must be tagged

### `develop`

- Active development branch
- New features, refactors, plugins, themes
- May be unstable

### Optional support branches

- `feature/<name>` -> merge into `develop`
- `hotfix/<name>` -> merge directly into `main`, then back-merge into `develop`

### Suggested release process

1. Build and test on `develop`.
2. Merge `develop` into `main` when stable.
3. Tag release on `main` (for example `v0.2.0`).
4. Continue feature work on `develop`.

## Setup

1. Create and activate a virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
2. Install dependencies:
    ```bash
    pip install -e ".[dev]"
    ```
3. Copy `.env.example` to `.env` and adjust if needed.

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open:

- Web setup/dashboard: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`

## REST API usage

### Send command

```bash
curl -X POST http://localhost:8000/api/v1/commands \
  -H "Content-Type: application/json" \
  -d '{"type":"scratch","intensity":0.7,"source":"api"}'
```

Response:

```json
{
    "accepted": true,
    "command_id": "...",
    "state_version": 12
}
```

Supported core command types:

- `feed`
- `play`
- `sleep`
- `wake`
- `scratch`
- `status`

### Export state snapshot

```bash
curl http://localhost:8000/api/v1/state/export
```

### Import state snapshot

```bash
curl -X POST http://localhost:8000/api/v1/state/import \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"snapshot":{...}}'
```

## Web setup wizard flow

1. Open `/setup`.
2. Enter pet name.
3. Select theme.
4. Enable or disable plugins.
5. Select hardware profile placeholder.
6. Submit and redirect to `/dashboard`.

## Plugin system

- Plugin folder pattern: `./plugins/<plugin_id>`
- Required files:
    - `manifest.json`
    - entrypoint file (default `plugin.py`)

`manifest.json` fields:

- `id`
- `name`
- `version`
- `description`
- `entrypoint`
- `class_name`
- `capabilities`

Plugin class must inherit `PluginBase` and can extend:

- commands
- emotions
- mini-games
- hardware drivers
- UI extensions

Manage plugins in web UI:

- `GET /plugins`
- `POST /plugins/rescan`
- `POST /plugins/{plugin_id}/enable`
- `POST /plugins/{plugin_id}/disable`

## Theme system

- Theme folder pattern: `./themes/<theme_id>`
- Required files:
    - `manifest.json`
    - assets folder (for example `assets/style.css`)

`manifest.json` fields:

- `id`
- `name`
- `version`
- `description`
- `preview`
- `stylesheet`

Manage themes in web UI:

- `GET /themes`
- `POST /themes/rescan`
- `POST /themes/{theme_id}/activate`

## State persistence and transfer

- State is persisted after every command and every tick.
- Every persisted state write creates a snapshot entry.
- State is versioned with `state_version` and `schema_version`.
- Export/import payload is platform independent JSON.
- Snapshot stores `active_theme_id` and `enabled_plugin_ids` by IDs.

## Testing

```bash
pytest
```

## Scope boundaries

- No real ePaper hardware integration yet (dummy driver only)
- No advanced auth or user management
- Designed to be extended incrementally without hidden magic
