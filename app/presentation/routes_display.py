from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.presentation.dependencies import get_container

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))

router = APIRouter(tags=["display"])


@router.get("/display")
async def display_page(request: Request, container=Depends(get_container)):
    return templates.TemplateResponse(
        request=request,
        name="display.html",
        context={
            "app_name": container.config.app_name,
            "capabilities": container.get_display_capabilities(),
            "frame_meta": container.get_display_frame_meta(),
        },
    )


@router.get("/api/display/capabilities")
async def get_display_capabilities(container=Depends(get_container)) -> JSONResponse:
    return JSONResponse(content=container.get_display_capabilities())


@router.get("/api/display/frame.png")
async def get_display_frame(container=Depends(get_container)) -> Response:
    meta = container.get_display_frame_meta()
    payload = container.get_display_frame_png()
    return Response(
        content=payload,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "ETag": container.framebuffer.hash(),
            "X-Display-Version": str(meta["version"]),
        },
    )


@router.get("/api/display/frame.meta")
async def get_display_meta(container=Depends(get_container)) -> JSONResponse:
    return JSONResponse(content=container.get_display_frame_meta())


@router.websocket("/ws/display")
async def display_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    container = websocket.app.state.container
    last_seen_version = -1

    try:
        while True:
            update = await container.wait_for_display_update(last_seen_version=last_seen_version, timeout_seconds=15.0)
            if update is None:
                await websocket.send_json({"event": "keepalive", "version": last_seen_version})
                continue

            last_seen_version = int(update["version"])
            await websocket.send_json({"event": "frame_updated", **update})
    except WebSocketDisconnect:
        return
