# Clawgotchi – Architecture & Project Guide
## 1. Purpose of this document
This document captures the current, code-verified architecture of Clawgotchi so future agents can generate accurate prompts and implement consistent changes.

Scope:
- Runtime startup and execution model
- Domain/state model and rendering pipeline
- REST API and web UI integration
- Plugin/theme/hardware integration boundaries
- Persistence and operations
- Architecture documentation update rules

## 2. High-level overview
Clawgotchi is a FastAPI-based pet runtime with:
- Layered architecture (`app/domain`, `app/application`, `app/infrastructure`, `app/presentation`)
- SQLite persistence for current state, snapshots, settings, plugin/theme registry data
- Shared in-memory 1-bit framebuffer used by both hardware output and web mirror
- Plugin-based hardware backend selection (dummy by default, Waveshare ePaper implemented as plugin)
- Theme manifests for sprite/fullframe rendering
- Tick loop + async command queue workers for state progression

Primary entrypoint: `main.py`.

## 3. Repository layout (directories & responsibilities)
Top-level directories and key files:
- `main.py`: FastAPI app creation, router wiring, websocket endpoints, static mounts, uvicorn startup.
- `app/`: Main layered application code.
- `core/`: Shared framebuffer and display fan-out manager.
- `plugins/`: Filesystem plugins (example plugin + Waveshare hardware plugin).
- `themes/`: Theme packages (`manifest.json` + assets).
- `docs/`: Project documentation (`ARCHITECTURE.md`, `DESIGN.md`).
- `config/`: Runtime defaults and display settings model.
- `clawgotchi/tools/`: CLI utilities (`display_test.py`, `doctor.py`, `plugin_deps.py`).
- `tests/`: Unit/integration tests for API, rendering, plugins, theme loading, SPI helper, UI flows.
- `install`, `install.ps1`: One-line bootstrap entrypoints for Unix-like shells and Windows PowerShell.
- `install.sh`, `update.sh`: Raspberry Pi install/update automation and systemd integration.
- `scripts/install_bootstrap.sh`, `scripts/install_bootstrap.ps1`, `scripts/common_install.py`: Cross-platform user-space bootstrap installation.
- `CONTRIBUTING.md`: Contributor workflow and architecture-doc maintenance rules.
- Runtime data is stored in per-user runtime home (not repo root).

Main runtime/entrypoint:
- `main.py`
- `app/container.py` (dependency container + lifecycle)

REST API location:
- Bootstrap/router registration: `main.py`
- Versioned API routes: `app/presentation/api.py`
- Display/input API routes: `app/presentation/routes_display.py`, `app/presentation/routes_input.py`
- Request/response schemas: `app/presentation/schemas.py`

Web interface location:
- Web routes: `app/presentation/web.py`
- Templates: `app/presentation/templates/*.html`
- Static assets: `app/presentation/static/*`
- Served from app mounts/routes in `main.py` (`/static`, `/theme-assets/{asset_path:path}` with multi-root lookup)

State persistence location:
- DB bootstrap: `app/infrastructure/database.py`
- SQLAlchemy models: `app/infrastructure/models.py`
- Repositories: `app/infrastructure/repositories.py`
- Domain serialization: `app/domain/entities.py`, `app/domain/models/pet_state.py`, `app/domain/snapshots.py`

Plugin system location:
- Manifest scan/load: `app/infrastructure/plugin_loader.py`
- Runtime lifecycle and activation: `app/application/services/core.py` (`PluginRuntime`, `PluginService`)
- Interface contracts: `app/application/interfaces.py`

Theme/pet assets location:
- Theme manifest and frame loading: `app/infrastructure/themes/theme_loader.py`
- Theme registry scan: `app/infrastructure/theme_loader.py`
- Rendering: `app/application/services/render_service.py`, `app/application/pet/pet_sprite_renderer.py`
- Built-in themes: `themes/default`, `themes/classic`

Hardware/display integration location:
- Display abstraction contract: `app/application/ports/display.py`
- Shared fan-out boundary: `core/display_manager.py`, `app/infrastructure/display/sinks.py`
- Dummy backend: `app/infrastructure/display/dummy.py`
- Waveshare plugin: `plugins/hardware/waveshare_epaper_27bw/*`
- Pi SPI helper: `app/infrastructure/system/pi_spi.py`
- GPIO button input: `app/infrastructure/input/gpio_buttons.py`

Configuration location:
- Resolver/env merge: `app/config.py`
- Static defaults: `config/defaults.toml`
- Display settings validation: `config/settings.py`
- Env example: `.env.example`

Tests and scripts:
- Tests: `tests/*.py`
- Install/update scripts: `install.sh`, `update.sh`
- Hardware display test: `clawgotchi/tools/display_test.py`

## 4. Runtime model (how the app starts)
Startup flow:
1. `main.py:create_app()` resolves config (`ConfigResolver`), validates runtime home writability, and ensures runtime directories exist.
2. FastAPI lifespan creates `ApplicationContainer` (`app/container.py`).
3. `ApplicationContainer.__init__`:
- Creates DB schema.
- Builds repositories/loaders/services.
- Creates base display driver (dummy), shared framebuffer, render service, input router/menu controller.
4. `ApplicationContainer.startup()`:
- Rescans plugins/themes.
- Loads or creates device state.
- Sanitizes enabled plugin IDs and hardware profile.
- Activates persisted hardware profile if possible.
- Refreshes display driver.
- Sets theme and renders first frame.
- Starts GPIO button driver.
- Starts background tasks:
  - `CommandWorker` (async command queue)
  - `TickWorker` (periodic tick loop)
5. Routers and websockets are already mounted:
- `/api/v1/*` (status/commands/export/import/plugins/themes)
- `/api/display/*`, `/api/input/button`
- `/ws/display`, `/ws/status`
- Web pages (`/`, `/setup`, `/dashboard`, `/plugins`, `/themes`, `/settings`)
6. On shutdown, workers are canceled, plugin runtime is stopped, GPIO button driver is stopped.

## 5. Core domain concepts
### Pet/Clawgotchi state model
Core domain state (`app/domain/entities.py`):
- `Pet`: id, name, emotion, needs (`hunger`, `energy`, `social`, `cleanliness`), sleeping flag.
- `DeviceState`: wraps `Pet` + render state (`PetState`) + metadata:
  - `schema_version`
  - `state_version`
  - `active_theme_id`
  - `enabled_plugin_ids`
  - `hardware_profile`
- `PetState` (`app/domain/models/pet_state.py`) tracks runtime animation state:
  - current animation name
  - animation end timestamp (temporary animation window)
  - frame index/start timestamp
  - last render timestamp

### Events & scheduling (if present)
Domain events exist as lightweight records (`app/domain/events.py`) and are persisted in snapshots.

Scheduling/processing model:
- Command queue (`AsyncCommandQueue`) + worker (`CommandWorker`) in `app/application/command_processing.py`.
- Tick loop worker (`TickWorker`) triggers `TickLoopService.run_tick()` at configured interval (`CLAW_TICK_INTERVAL_SECONDS`, default 2s).
- Command and tick flows both:
  - load state
  - apply core/domain mutations
  - call plugin hooks
  - trigger render decision/push
  - persist snapshot

Not implemented yet:
- No cron-like scheduler/event bus beyond queue + fixed tick loop.

### Rendering pipeline (virtual canvas vs ePaper)
Pipeline:
1. `RenderService` computes animation frame selection.
2. `ScreenRenderer` builds full canvas:
- Left sidebar menu (always visible)
- Pet rendering in content rect only
- Optional notifications overlay in content rect
3. Result is written into `FrameBuffer1Bit` (`core/framebuffer.py`).
4. `DisplayManager` pushes the same framebuffer to active sinks.
5. Active sink bridges to selected display driver via `DisplayDriverSink`.

Virtual/web mirror:
- `GET /api/display/frame.png` and websocket `/ws/display` expose framebuffer updates.

Hardware:
- Active hardware plugin display driver receives the same framebuffer image data.
- Dummy backend optionally writes `/tmp/clawgotchi_last_frame.png`.

## 6. REST API
### Base URL
- App base: `http://<host>:<port>` (defaults from config: `0.0.0.0:8000`)
- Versioned API: `/api/v1`
- Additional runtime endpoints outside `/api/v1`:
  - `/api/display/*`
  - `/api/input/button`

### Auth (if any)
- API key is optional and only enforced when `CLAW_API_KEY` is non-empty.
- Enforcement currently applies to `/api/v1/*` routes (`app/presentation/dependencies.py`).
- Header: `x-api-key: <value>`

Not implemented yet:
- No auth layer on `/api/display/*`, `/api/input/button`, or web routes.

### Key endpoints (method, path, request/response shape)
Versioned API (`app/presentation/api.py`):
- `GET /api/v1/status` -> `{ setup_completed, state, state_version }`
- `POST /api/v1/commands`
  - request: `{ type: str, intensity: float[0..1], source: str }`
  - response: `{ accepted: bool, command_id: str, state_version: int }`
- `GET /api/v1/state/export`
  - response: `{ snapshot_id, schema_version, state_version, created_at, state }`
- `POST /api/v1/state/import`
  - request: `{ snapshot: object, dry_run: bool }`
  - response (dry-run): `{ dry_run: true, valid: true, ... }`
  - response (import): `{ imported: true, state_version, schema_version, imported_at, ... }`
- `GET /api/v1/plugins` -> list of plugin rows (`plugin_id`, `enabled`, `manifest`, etc.)
- `GET /api/v1/themes` -> list of theme rows (`theme_id`, `active`, `manifest`, etc.)

Display/input API:
- `GET /api/display/capabilities` -> `{ width, height, mode }`
- `GET /api/display/frame.png` -> latest framebuffer PNG (`X-Display-Version`, `ETag`)
- `GET /api/display/frame.meta` -> `{ version, updated_at_ms, width, height }`
- `POST /api/input/button`
  - request: `{ button: "NEXT"|"BACK"|"CONFIRM"|"SPECIAL" }`
  - response: `{ ok: true }`

WebSocket streams:
- `/ws/display` -> frame update notifications + keepalive
- `/ws/status` -> periodic status JSON

### Example curl calls (realistic based on code)
```bash
# Optional auth header only if CLAW_API_KEY is configured.
curl -s http://localhost:8000/api/v1/status

curl -s -X POST http://localhost:8000/api/v1/commands \
  -H "Content-Type: application/json" \
  -d '{"type":"feed","intensity":0.8,"source":"api"}'

curl -s http://localhost:8000/api/v1/state/export > /tmp/clawgotchi-export.json

curl -s -X POST http://localhost:8000/api/v1/state/import \
  -H "Content-Type: application/json" \
  -d "{\"snapshot\":$(cat /tmp/clawgotchi-export.json),\"dry_run\":true}"

curl -s http://localhost:8000/api/display/frame.meta

curl -s -X POST http://localhost:8000/api/input/button \
  -H "Content-Type: application/json" \
  -d '{"button":"NEXT"}'
```

## 7. Web UI
### Tech stack
- FastAPI + Jinja2 server-rendered templates.
- Plain JavaScript for interactive behavior (`dashboard_display.js`, `ui.js`).
- CSS in `app/presentation/static/styles.css`.

### Where it is mounted/served
- Web routes in `app/presentation/web.py`.
- Template directory: `app/presentation/templates/`.
- Static assets mounted in `main.py`:
  - `/static` -> `app/presentation/static`
- `/theme-assets/{asset_path:path}` -> first matching file across configured theme roots (runtime first, built-in fallback)

### Key screens/components (init, dashboard card, menu controls)
- Setup/init flow:
  - `GET /setup` + `POST /setup`
  - template: `app/presentation/templates/setup.html`
- Dashboard display card:
  - `GET /dashboard`
  - template: `app/presentation/templates/dashboard.html`
  - center display mirror image `#dashboard-display-frame`
- Menu controls:
  - Dashboard virtual buttons with `data-button` values (`BACK`, `NEXT`, `CONFIRM`, `SPECIAL`)
  - JS posts to `/api/input/button`
  - Keyboard mapping:
    - `ArrowDown` -> `NEXT`
    - `ArrowUp` -> `BACK`
    - `Enter` -> `CONFIRM`
    - `Space` -> `SPECIAL`

Other pages:
- `/plugins` (`plugins.html`)
- `/themes` (`themes.html`)
- `/settings` (`settings.html`, includes hardware selection and update controls)

## 8. Display & Menu System
### Unified menu model shared by web + hardware display
The menu is rendered into the shared framebuffer, so hardware output and web mirror always show the same menu state.

Model/controller:
- Input enum and event model: `app/domain/ui/input.py`
- Menu entries: `app/domain/ui/menu.py`
- State/navigation/notifications: `app/application/ui/menu_controller.py`
- Frame composition: `app/application/render/screen_renderer.py`

### Input model (4 buttons: next, back, confirm, special) + mapping
Button IDs:
- `NEXT`
- `BACK`
- `CONFIRM`
- `SPECIAL`

Input sources:
- Physical GPIO buttons (`app/infrastructure/input/gpio_buttons.py`)
- HTTP input endpoint (`POST /api/input/button`)
- Dashboard keyboard shortcuts and virtual buttons (`dashboard_display.js`)

Menu behavior:
- `NEXT`/`BACK`: selection navigation
- `CONFIRM`: trigger action/toggle/enter submenu
- `SPECIAL`:
  - root menu: toggle notifications overlay
  - submenu: jump back to root

### Sidebar layout rules (left vertical bar)
Layout rules in `app/application/render/layout.py`:
- `sidebar_width = clamp(round(width * 0.18), 40, 72)`
- Sidebar occupies left vertical band.
- Pet content is rendered only in the remaining right-side content rectangle.

Sidebar renderer (`MenuSidebarRenderer`):
- Draws title, visible menu items, selection highlight, indicators, notification badge.

## 9. Plugin system
### Plugin packaging (zip/git/plugin manager ready: planned vs implemented)
Implemented now:
- Filesystem plugin discovery by scanning `manifest.json` files across ordered plugin roots (runtime first, built-in fallback).
- Runtime enable/disable/rescan through service + web actions.
- Plugin dependency helper CLI installs into managed runtime virtualenv: `python -m clawgotchi.tools.plugin_deps install <plugin_id>`.

Not implemented yet:
- Zip installer, Git-based plugin fetcher, or dedicated plugin package manager workflow.
- Signature verification/trust model for plugin sources.

### plugin manifest format and required fields
Parsed by `FileSystemPluginLoader` (`app/infrastructure/plugin_loader.py`).

Required in practice:
- `id` (fallback: folder name)
- `name` (fallback: plugin id)
- `version` (fallback: `0.0.0`)
- `entrypoint` (fallback: `plugin.py`)
- `class_name` (fallback: `Plugin`)

Optional/common:
- `description`
- `capabilities` (list)
- `python_dependencies` (list of pip requirement specifiers used by `plugin_deps` helper)
- extra keys are kept in `metadata` (for example `hardware_profiles`)

### discovery/loading lifecycle
1. Scan manifests on startup/rescan (`PluginService.rescan()`).
   - Duplicate plugin IDs are resolved by root order (runtime overrides built-in).
2. Persist manifests in DB (`plugins` table).
3. Set runtime manifest registry.
4. Synchronize enabled plugin instances:
- start enabled plugins (`on_startup`)
- stop disabled plugins (`on_shutdown`)
5. During runtime:
- `on_tick(state)` called by tick loop
- `on_command(state, command)` called during command processing

### extension points (hardware, games, emotions, UI panels, renderers)
`PluginBase` extension points in `app/application/interfaces.py`:
- `on_startup`, `on_shutdown`, `on_tick`, `on_command`
- Metadata-style providers: `get_commands`, `get_emotions`, `get_mini_games`, `get_hardware_drivers`, `get_ui_extensions`
- `create_display_driver(profile_id, settings)` for hardware backend injection

Current implementation status:
- Hardware display extension point is actively used (`create_display_driver`).
- Command/tick hooks are used.
- Metadata getters (games/emotions/UI panels) are currently not wired into API/UI menus.

## 10. Themes / Pets
### Theme manifest format (e.g., assets/sprites paths, canvas size 264x176, 1-bit)
Theme manifest model (`app/infrastructure/themes/theme_loader.py`) supports:
- `id`, `name`, `version`, `description`, `preview`, `stylesheet`
- `canvas_width`, `canvas_height` (defaults 264x176)
- `default_animation`
- `render`:
  - `base_sprite_size` `[w, h]`
  - `dither` (bool)
  - `threshold` (0..255)
- `placement`:
  - `mode`: `sprite` or `legacy_fullframe` (legacy `fullframe` normalized)
  - `anchor`, `offset_x`, `offset_y`, `scale_mode`, `scale`
- `animations`: map of animation name -> `{ fps, frames[], duration_ms? }`

Current built-in themes:
- `themes/default/manifest.json` (sprite mode)
- `themes/classic/manifest.json` (legacy fullframe mode)

Theme discovery/loading behavior:
- Theme manifests are scanned across ordered theme roots (runtime first, built-in fallback).
- Theme assets are resolved through the same ordered roots.

### Placement/anchor rules
Sprite placement is resolved by `PetSpriteRenderer`:
- Anchors: `center`, `top_center`, `bottom_left`, `bottom_right`, `bottom_center` (default)
- Scale clamped by content rect
- Placement is constrained to content area (sidebar excluded)

### Animation handling on ePaper (frame strategy, partial refresh if used)
Frame selection:
- Based on animation FPS and elapsed time since animation start.
- Idle default FPS fallback: `0.33`.
- Scratch animation supports `duration_ms`; fallback default `1200ms`.

Render cadence decision (`RenderService.should_render`):
- Scratch minimum interval: `1000ms`
- Other animations minimum interval: `2800ms`
- Render if frame changed or interval elapsed.

Hardware refresh strategy:
- Waveshare driver uses partial refresh only when:
  - `display_use_partial` is true
  - backend provides a partial method
- Otherwise full refresh (`display()`).

## 11. Hardware integration (Waveshare ePaper HAT)
### Abstraction boundary (core vs plugin)
Boundary:
- Core/application depends only on `DisplayDriver` interface (`app/application/ports/display.py`).
- Hardware plugin supplies concrete driver instance through `create_display_driver`.
- `DisplayManager` and `DisplayDriverSink` keep hardware output behind sink abstraction.

### What is required on the Pi (dependencies) and how installation is handled
Python deps (declared):
- `waveshare-epaper`
- `gpiozero`
- optionally `spidev` (plugin manifest dependency)

OS/runtime expectations:
- Raspberry Pi hardware
- SPI enabled (`/dev/spidev*`)
- user access to `spi`/`gpio` groups
- optional sudoers policy for non-interactive SPI enabling and update service start

Install handling:
- `scripts/install_bootstrap.sh` and `scripts/install_bootstrap.ps1` perform cross-platform user-space installation/update without system directories.
- Shared bootstrap logic in `scripts/common_install.py` creates runtime home, venv, launchers, and runtime `.env`.
- `install.sh` remains available for optional Raspberry Pi SPI/systemd provisioning.
- Waveshare driver (`plugins/hardware/waveshare_epaper_27bw/driver.py`) performs runtime SPI checks and best-effort enablement via `PiSpiManager`.

### Diagnostics / logging approach for hardware
- Structured JSON logging via `app/infrastructure/logging.py`.
- Hardware backend status stored in container state (`ApplicationContainer._hardware_status`) and surfaced on settings page context.
- CLI diagnostic tool:
  - `python -m clawgotchi.tools.display_test --backend waveshare_epaper_27bw`
- Useful operational logs:
  - `journalctl -u clawgotchi -f`
  - `journalctl -u clawgotchi-update.service -n 50`

## 12. State persistence & export/import
### Storage location and format (json/sqlite/etc.)
Default persistence:
- SQLite database URL default: runtime-home scoped absolute path
  - example (Unix): `sqlite:////home/<user>/.local/share/clawgotchi/db/clawgotchi.db`
- Tables:
  - `current_state`
  - `state_snapshots`
  - `settings`
  - `plugins`
  - `themes`

Serialized data:
- `DeviceState` and events are stored as JSON payloads in DB rows.

### Versioning/migrations strategy (if present)
Implemented:
- In-state versioning via `schema_version` and `state_version`.
- Export/import enforces supported schema version (`StateTransferService.SUPPORTED_SCHEMA_VERSION = 1`).

Not implemented yet:
- No explicit DB migration framework (for example Alembic).
- Schema is created with `Base.metadata.create_all()` at startup.

### Export/import workflow
Export:
- `GET /api/v1/state/export` -> state snapshot object.

Import:
- `POST /api/v1/state/import` with `{snapshot, dry_run}`.
- Dry run validates schema and payload conversion only.
- Real import:
  - restores state
  - syncs enabled plugin flags
  - re-synchronizes runtime plugin instances
  - activates active theme when available
  - updates setup settings values

## 13. Configuration
### Config files and environment variables
Resolution order (`app/config.py`):
1. Built-in defaults
2. `config/defaults.toml`
3. `.env` / environment variables (`CLAW_` prefix)
4. DB overrides from `settings` table (`config.*` keys)
5. Explicit runtime overrides (for tests/startup)

Primary files:
- `config/defaults.toml`
- `.env.example`

Key env vars:
- App/network: `CLAW_APP_NAME`, `CLAW_HOST`, `CLAW_PORT`, `CLAW_LOG_LEVEL`
- Runtime: `CLAW_RUNTIME_HOME`, `CLAW_TICK_INTERVAL_SECONDS`, `CLAW_DATABASE_URL`
- Paths: `CLAW_PLUGIN_DIRECTORY`, `CLAW_THEME_DIRECTORY`, `CLAW_PLUGIN_DIRECTORIES`, `CLAW_THEME_DIRECTORIES`, `CLAW_CONFIG_FILE`, `CLAW_ENV_FILE`
- Security: `CLAW_API_KEY`
- Display/GPIO/SPI: `CLAW_DISPLAY_*`, `CLAW_BUTTON_GPIO_*`

### Defaults and examples
Default examples are documented in:
- `config/defaults.toml`
- `.env.example`

Runtime home defaults:
- Linux: `${XDG_DATA_HOME:-~/.local/share}/clawgotchi`
- macOS: `~/Library/Application Support/Clawgotchi`
- Windows: `%LOCALAPPDATA%\\Clawgotchi`

## 14. Observability & operations
### How to run locally
Typical local run:
```bash
python main.py
```

Installed launcher run:
```bash
clawgotchi
```

Tests:
```bash
pytest
```

### How to run on Raspberry Pi (service, systemd if used)
Optional Pi provisioning script (`install.sh`) provisions:
- `clawgotchi.service` for app runtime
- `clawgotchi-update.service` + `clawgotchi-update.timer` for nightly updates

Update workflow:
- rerun bootstrap installer one-liner (cross-platform, idempotent)
- `./update.sh` (manual, supports runtime venv fallback)
- or systemd timer/service managed update

### Logging locations
- App logs to stdout/stderr in JSON format.
- On systemd hosts:
  - `journalctl -u clawgotchi -f`
  - `journalctl -u clawgotchi-update.service -n 50`

### “Live monitoring” commands if applicable
```bash
curl -s http://localhost:8000/api/v1/status
curl -s http://localhost:8000/api/display/frame.meta
```

Optional websocket monitoring:
- `/ws/status`
- `/ws/display`

## 15. Development workflow
### Branching model (main = publish, dev branch = development)
Branch policy:
- `main`: publish/release branch
- `dev`: development/integration branch

### Formatting/linting/test commands
Configured now:
- `pytest` (from `pyproject.toml`)

Not implemented yet:
- No configured formatter/linter command in repository config (no `ruff`, `black`, `flake8`, etc. config in `pyproject.toml`).

### How to add plugins/themes
Plugins:
1. Add folder under runtime plugin directory (default `<runtime_home>/plugins`) with `manifest.json` and entrypoint module/class.
2. Rescan via `/plugins/rescan` or service-level rescan on startup.
3. Enable plugin via `/plugins/{plugin_id}/enable` or setup flow.
4. If plugin declares `python_dependencies`, install into runtime venv via `python -m clawgotchi.tools.plugin_deps install <plugin_id>`.

Themes:
1. Add folder under runtime theme directory (default `<runtime_home>/themes`) with `manifest.json` and assets.
2. Rescan via `/themes/rescan`.
3. Activate via `/themes/{theme_id}/activate` or setup flow.

Theme authoring reference:
- `CONTRIBUTING.md`

## 16. Updating this document
### Definition of “relevant code change”
A change is architecture-relevant if staged diff includes:
- `app/**`
- `core/**`
- `plugins/**`
- `themes/**`
- `config/**`
- `clawgotchi/**`
- `main.py`
- `install.sh`
- `update.sh`

### Required update procedure
When relevant code changes:
1. Update `docs/ARCHITECTURE.md` in the same commit.
2. Verify section accuracy against code paths changed.
3. Keep “Not implemented yet” / “Planned” notes explicit for any incomplete areas.

### Automation/check details
Implemented pre-commit enforcement:
- Check script: `scripts/check_architecture_doc_updated.sh`
- Hook entrypoint: `.githooks/pre-commit`

Behavior:
- If staged changes touch relevant architecture paths and `docs/ARCHITECTURE.md` is not staged, commit is blocked with guidance.

One-time setup per clone:
```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit scripts/check_architecture_doc_updated.sh
```
