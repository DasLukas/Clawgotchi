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
