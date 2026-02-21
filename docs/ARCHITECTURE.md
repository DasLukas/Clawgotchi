# Clawgotchi Architecture

## System Overview
Clawgotchi is a layered FastAPI application with SQLite persistence, a shared 1-bit framebuffer, and a web mirror.

Key runtime properties:
- Layered code organization: `domain`, `application`, `infrastructure`, `presentation`.
- Stateful runtime with persistent snapshots and versioned state (`schema_version`, `state_version`).
- Rendering pipeline writes to one in-memory framebuffer that is consumed by web endpoints and the active display sink.
- Hardware integration is plugin-based. The built-in fallback backend is `dummy`.

Primary runtime entrypoints:
- `main.py`: app factory, routes, websocket endpoints, static mounts.
- `app/container.py`: dependency assembly, startup/shutdown lifecycle, worker orchestration.

## Module Structure

### Domain Layer (`app/domain`)
Purpose:
- Core business entities and value objects.

Main responsibilities:
- Device and pet state representation.
- Domain events and state serialization.
- Input enums and UI-domain models.

Important modules:
- `app/domain/entities.py`
- `app/domain/events.py`
- `app/domain/models/pet_state.py`
- `app/domain/value_objects.py`

### Application Layer (`app/application`)
Purpose:
- Use-case orchestration and cross-layer contracts.

Main responsibilities:
- Command/tick processing.
- Plugin runtime lifecycle and enable/disable flow.
- Rendering decision logic and state transitions.
- Service APIs used by web/API adapters.

Important modules:
- `app/application/services/core.py`
- `app/application/services/render_service.py`
- `app/application/interfaces.py`
- `app/application/command_processing.py`

### Infrastructure Layer (`app/infrastructure`)
Purpose:
- External systems, persistence, I/O adapters, filesystem plugin/theme discovery.

Main responsibilities:
- SQLAlchemy repositories and DB schema.
- Display drivers/sinks (dummy built-in).
- Plugin and theme manifest loading from filesystem roots.
- Optional hardware input adapters (plugin-provided; lazy hardware imports).

Important modules:
- `app/infrastructure/database.py`
- `app/infrastructure/repositories.py`
- `app/infrastructure/plugin_loader.py`
- `app/infrastructure/theme_loader.py`
- `app/infrastructure/display/dummy.py`
- `app/infrastructure/display/sinks.py`

### Presentation Layer (`app/presentation`)
Purpose:
- HTTP and websocket adapters, HTML templates, static assets.

Main responsibilities:
- Versioned API routes under `/api/v1/*`.
- Display mirror endpoints under `/api/display/*`.
- Unified button input endpoint under `/api/input/button`.
- Setup/dashboard/settings HTML routes.

Important modules:
- `app/presentation/api.py`
- `app/presentation/routes_display.py`
- `app/presentation/routes_input.py`
- `app/presentation/web.py`

### Shared Core (`core`)
Purpose:
- Shared display primitives independent from framework and storage.

Main responsibilities:
- 1-bit framebuffer and change tracking.
- Fan-out display manager to push rendered frames to sinks.

Important modules:
- `core/framebuffer.py`
- `core/display_manager.py`

## Data Flow

### Startup Flow
1. `main.py` resolves configuration and creates `ApplicationContainer`.
2. Container initializes DB, repositories, loaders, render services, and dummy display sink.
3. Plugins and themes are scanned from configured roots.
4. Existing state is loaded (or created), sanitized, and synchronized with available plugins/themes.
5. Active hardware profile is restored (`dummy` by default).
6. Initial frame is rendered and published to framebuffer/sinks.
7. Background workers start:
   - command worker
   - periodic tick worker

### Command Flow (`/api/v1/commands`)
1. Presentation validates payload and creates `PetCommand`.
2. Command queue enqueues work.
3. Command handler loads state, applies domain mutation, invokes plugin hooks.
4. Render service decides and renders frame when needed.
5. New state snapshot is persisted and state version is incremented.

### Tick Flow
1. Tick worker executes at configured interval.
2. State is loaded and domain tick rules are applied.
3. Plugin tick hooks are invoked.
4. Render decision is evaluated and frame is pushed if necessary.
5. State and events are persisted.

### Display Flow
1. Rendered image is written into `FrameBuffer1Bit`.
2. `DisplayManager` propagates framebuffer updates to active sinks.
3. Web mirror endpoints expose PNG/meta snapshots.
4. The active hardware profile driver (if provided by an enabled plugin) receives the same frame.

### Input Flow
1. Web buttons post to `/api/input/button` (`NEXT`, `BACK`, `CONFIRM`, `SPECIAL`).
2. Optional hardware adapters can publish the same button events.
3. Input router forwards events to menu/controller logic.
4. Subsequent ticks/commands react to queued input events.

## External Dependencies

Core runtime dependencies:
- `fastapi`, `uvicorn`, `jinja2`
- `sqlalchemy`
- `pydantic`, `pydantic-settings`
- `pillow`
- `python-multipart`

Development dependencies:
- `pytest`
- `httpx`

Storage and runtime:
- SQLite database in runtime home.
- Runtime directories for logs/cache/plugins/themes/config.

Operational constraints:
- Tests must run without physical hardware.
- Hardware-specific imports must remain lazy inside hardware adapters/plugins.

Program workspace defaults:
- macOS: `~/Library/Application Support/Clawgotchi`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi`
- Windows: `%LOCALAPPDATA%\Clawgotchi`

Workspace structure includes runtime data plus source checkout (`.../src`).

## Plugin and Extension Architecture

### Plugin Discovery
Plugin manifests are discovered from configured plugin roots in order:
1. Runtime plugin directory (user-writable)
2. Built-in repository plugin directory

Earlier roots take precedence on duplicate IDs.

Plugin metadata source:
- `manifest.json` in plugin folders.

### Plugin Runtime Contract
All plugins implement `PluginBase` (`app/application/interfaces.py`).

Supported extension points:
- lifecycle: `on_startup`, `on_shutdown`
- behavior: `on_tick`, `on_command`
- optional lists: commands/emotions/mini-games/ui extensions
- hardware: `get_hardware_drivers`, `create_display_driver`

### Hardware Profiles
- `dummy` is always available as a safe fallback.
- Additional hardware profiles are declared by plugin manifest metadata (`hardware_profiles`).
- Activating a non-dummy profile auto-enables its provider plugin.
- If a profile fails at runtime, the container falls back to `dummy` and records hardware status.

### Themes
Theme manifests are loaded similarly from ordered theme roots:
1. Runtime theme directory
2. Built-in repository theme directory

Themes provide:
- manifest metadata
- animation assets
- optional stylesheet for UI branding

### Pet Asset Authoring and Runtime Pipeline
Pet visuals are implemented as theme assets. New pet art is added by creating a theme folder with a `manifest.json` and frame images under `assets/`.

Authoring contract:
- Asset root: `themes/<theme_id>/`
- Theme metadata: `themes/<theme_id>/manifest.json`
- Animation frame files: paths listed in `animations.<name>.frames` (usually `assets/<animation>_<index>.png`)
- Optional shared frame reuse via relative paths (for example `../classic/assets/idle_0.png`)

Runtime pipeline:
1. `FileSystemThemeLoader` scans ordered theme roots and registers available theme manifests.
2. `ThemeLoader` (`app/infrastructure/themes/theme_loader.py`) parses and validates `ThemeManifest`, including declared frame paths.
3. Render services resolve the active animation and frame index from the current pet state.
4. `PetSpriteRenderer` loads the selected frame, applies placement/scale settings, then converts to 1-bit output using threshold/dither settings.
5. The resulting frame is written to the shared framebuffer and fanned out to web mirror and active hardware display sinks.

## API Surface Summary
- Versioned API: `/api/v1/*`
- Display API: `/api/display/*`
- Input API: `/api/input/button`
- Websocket streams: `/ws/display`, `/ws/status`

## Persistence and Versioning Guarantees
- `schema_version` remains stable and validated on import.
- `state_version` increments with persisted mutations.
- State export/import supports dry-run validation.
- Plugin/theme activation state is persisted in repository tables and device state snapshots.

## Architectural Boundaries
- No hardware-specific logic in domain or application core.
- Hardware integration must stay behind plugin/display-driver contracts.
- Presentation layer does not mutate domain directly; all state changes go through services.
- Infrastructure adapters must not leak persistence/framework concerns into domain models.

## Installation and Update Operations

Install and update are intentionally manual (Git-based) and are no longer handled by repository-managed bootstrap/update scripts.

Operational flow:
- Clone repository into a user-writable path.
- Create and use a local virtual environment.
- Install with editable mode (`python -m pip install -e .` or `python -m pip install -e \".[dev]\"`).
- Update by running `git pull --ff-only` in the checkout and reinstalling editable dependencies.

This removes script-specific orchestration from the architecture and keeps update behavior explicit and host-tool driven.

## 16. Architecture-Relevant Path Scope and Change Notes
- Architecture-relevant paths for commit checks:
  - `app/`
  - `core/`
  - `plugins/`
  - `themes/`
  - `config/`
  - `clawgotchi/`
  - `main.py`
- 2026-02-21: Removed repository-managed install/update script architecture (`install*`, `update.sh`, bootstrap helpers, and web-triggered update endpoints). Installation and updates now follow manual Git + virtualenv workflows documented in README.
- 2026-02-13: Reworked install/update behavior for dedicated per-user host workspace paths and managed workspace defaults, including update delegation, self-healing venv reinstall, and bootstrap auto re-clone for broken managed checkouts.
- 2026-02-13: Simplified desktop updates to a bootstrap-driven managed workflow, preserved private SSH remotes by default, and added explicit SSH auth environment hooks (`CLAW_GIT_SSH_COMMAND` / `CLAW_GIT_SSH_KEY`).
- 2026-02-13: Hardened installer/update shell behavior for stdin execution and strict-mode array handling (`set -u`), and improved Python interpreter resolution on macOS bootstrap installs.
- 2026-02-13: Removed the three decorative dots below the dashboard display by deleting the `tamagotchi-buttons` markup from `app/presentation/templates/dashboard.html`. This is presentation-only and does not affect module boundaries, APIs, data flow, persistence, or plugin architecture.
- 2026-02-13: Replaced the framebuffer menu rendering from a left vertical sidebar to a bottom horizontal icon bar in `app/application/render/layout.py` and `app/application/render/screen_renderer.py`, with corresponding renderer wiring/test updates. This is a UI layout change inside the existing render pipeline and does not alter layering, persistence, plugin contracts, or API endpoints.
- 2026-02-13: Updated virtual dashboard control buttons in `app/presentation/templates/dashboard.html` to icon labels (`◀`, `▶`, `✓`, `✦`) with minor typography tuning in `app/presentation/static/styles.css`. This is presentation-only and does not alter APIs, input routing, persistence, or architecture boundaries.
- 2026-02-21: Slimmed down the framebuffer bottom menu bar and simplified icon rendering in `app/application/render/layout.py` and `app/application/render/screen_renderer.py` to reduce visual density. This remains a presentation/rendering adjustment and does not change APIs, state persistence, or architectural boundaries.
