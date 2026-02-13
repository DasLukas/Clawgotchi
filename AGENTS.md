# AGENTS.md

## Project: Clawgotchi

Clawgotchi is a FastAPI application with strict layering:

- `domain`
- `application`
- `infrastructure`
- `presentation`

Persistence is SQLite-based. A shared 1-bit framebuffer is used to serve both the Web Mirror and hardware displays.

Hardware is always plugin-based (Dummy default, Waveshare ePaper as a plugin). Do not put hardware logic into core layers.

Input is unified for web and hardware: 4 buttons `NEXT`, `BACK`, `CONFIRM`, `SPECIAL`.

---

## Python Requirements

- Python `>= 3.11`

---

## Environment Setup

All commands must be executed from the repository root.

### Create and activate a virtual environment (Linux/macOS)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### Install the project including development dependencies

```bash
python -m pip install -e ".[dev]"
```

Notes:

- Always use `python -m ...` to ensure the correct interpreter.
- Do not rely on globally installed packages.

---

## Running Tests

Run tests via the venv Python interpreter.

Recommended:

```bash
python -m pytest -q
```

Verbose debugging:

```bash
python -m pytest -vv
```

Run a subset:

```bash
python -m pytest -q tests/test_runtime_config.py tests/test_plugin_loader.py
```

---

## Test Expectations and Constraints

1. Tests must run without physical hardware.
2. Do not import hardware drivers at module import time.
    - Hardware dependencies must be loaded only inside plugin implementations.
    - Use lazy imports within plugin factories/constructors.
3. Tests must not require external network access.
4. Tests must not depend on user-local paths.
5. SQLite in tests must use isolated, temporary runtime directories.

---

## Project Conventions

### API

- Versioned API routes live under `/api/v1/*`.
- Display and input routes:
    - Display: `/api/display/*`
    - Button input: `/api/input/button`

### Persistence and Versioning

State must remain:

- persisted
- exportable/importable

Do not break:

- `schema_version`
- `state_version`

### UI

The dashboard shows the display as a centered card (no separate display screen).

---

## What To Do If `pytest` Is Not Found

If `pytest` is not available in the shell PATH, do not call `pytest` directly.

Instead, run:

```bash
python -m pytest --version
python -m pytest -q
```

If `pytest` is missing, install dev dependencies:

```bash
python -m pip install -e ".[dev]"
```
