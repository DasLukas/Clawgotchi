from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ConfigResolver, assert_runtime_home_writable, ensure_runtime_layout
from app.container import ApplicationContainer
from app.presentation.api import router as api_router
from app.presentation.routes_display import router as display_router
from app.presentation.routes_input import router as input_router
from app.presentation.web import router as web_router


def _resolve_theme_asset_path(theme_roots: tuple[Path, ...], asset_path: str) -> Path | None:
    normalized = Path(asset_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        return None

    for root in theme_roots:
        base = root.resolve()
        candidate = (base / normalized).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def create_app(config_overrides: dict[str, Any] | None = None) -> FastAPI:
    resolver = ConfigResolver(extra_overrides=config_overrides)
    static_config = resolver.resolve()
    ensure_runtime_layout(static_config.runtime_home)
    assert_runtime_home_writable(static_config.runtime_home)
    static_config.plugin_directory.mkdir(parents=True, exist_ok=True)
    static_config.theme_directory.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = ApplicationContainer(config_overrides=config_overrides)
        app.state.container = container
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(title="Clawgotchi", version="0.1.0", lifespan=lifespan)

    app.include_router(api_router)
    app.include_router(display_router)
    app.include_router(input_router)
    app.include_router(web_router)

    static_directory = Path(__file__).resolve().parent / "app" / "presentation" / "static"
    app.mount("/static", StaticFiles(directory=str(static_directory)), name="static")

    @app.get("/theme-assets/{asset_path:path}", include_in_schema=False)
    async def theme_assets(asset_path: str) -> FileResponse:
        resolved = _resolve_theme_asset_path(static_config.theme_directories, asset_path)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Theme asset not found.")
        return FileResponse(path=resolved)

    @app.websocket("/ws/status")
    async def status_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        container: ApplicationContainer = app.state.container
        try:
            while True:
                await websocket.send_json(container.status_service.get_status())
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return app


app = create_app()


if __name__ == "__main__":
    config = ConfigResolver().resolve()
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )
