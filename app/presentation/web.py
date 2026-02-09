from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.application.services import SetupRequest
from app.domain.value_objects import PetCommand
from app.presentation.dependencies import get_container

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))

router = APIRouter(tags=["web"])


@router.get("/")
async def root(container=Depends(get_container)) -> RedirectResponse:
    if container.initialize_device_service.is_completed():
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/setup", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/setup")
async def setup_page(request: Request, container=Depends(get_container)):
    if container.initialize_device_service.is_completed():
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    themes = container.theme_service.list_themes()
    plugins = container.plugin_service.list_plugins()
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "app_name": container.config.app_name,
            "themes": themes,
            "plugins": plugins,
            "hardware_profiles": ["dummy", "raspberrypi-v1"],
        },
    )


@router.post("/setup")
async def setup_submit(
    container=Depends(get_container),
    pet_name: str = Form(...),
    theme_id: str = Form("default"),
    hardware_profile: str = Form("dummy"),
    plugin_ids: list[str] = Form(default=[]),
) -> RedirectResponse:
    await container.initialize_device_service.initialize(
        SetupRequest(
            pet_name=pet_name,
            theme_id=theme_id,
            plugin_ids=plugin_ids,
            hardware_profile=hardware_profile,
        )
    )
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard")
async def dashboard(request: Request, container=Depends(get_container)):
    if not container.initialize_device_service.is_completed():
        return RedirectResponse(url="/setup", status_code=status.HTTP_303_SEE_OTHER)

    status_payload = container.status_service.get_status()
    theme_stylesheet = ""
    for theme in container.theme_service.list_themes():
        if theme["theme_id"] == status_payload["state"]["active_theme_id"]:
            theme_stylesheet = theme["manifest"].get("stylesheet", "")
            break

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": container.config.app_name,
            "status": status_payload,
            "theme_stylesheet": theme_stylesheet,
        },
    )


@router.post("/dashboard/command")
async def dashboard_command(
    container=Depends(get_container),
    command_type: str = Form(...),
    intensity: float = Form(1.0),
) -> RedirectResponse:
    command = PetCommand(type=command_type, intensity=intensity, source="web")
    await container.send_command_service.send(command)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/plugins")
async def plugins_page(request: Request, container=Depends(get_container)):
    plugins = container.plugin_service.list_plugins()
    return templates.TemplateResponse(
        request=request,
        name="plugins.html",
        context={
            "app_name": container.config.app_name,
            "plugins": plugins,
        },
    )


@router.post("/plugins/rescan")
async def plugins_rescan(container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.rescan()
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/{plugin_id}/enable")
async def plugins_enable(plugin_id: str, container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.enable(plugin_id)
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/{plugin_id}/disable")
async def plugins_disable(plugin_id: str, container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.disable(plugin_id)
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/themes")
async def themes_page(request: Request, container=Depends(get_container)):
    themes = container.theme_service.list_themes()
    return templates.TemplateResponse(
        request=request,
        name="themes.html",
        context={
            "app_name": container.config.app_name,
            "themes": themes,
        },
    )


@router.post("/themes/rescan")
async def themes_rescan(container=Depends(get_container)) -> RedirectResponse:
    container.theme_service.rescan()
    return RedirectResponse(url="/themes", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/themes/{theme_id}/activate")
async def themes_activate(theme_id: str, container=Depends(get_container)) -> RedirectResponse:
    container.theme_service.activate_theme(theme_id)
    return RedirectResponse(url="/themes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/debug/frame")
async def debug_frame(container=Depends(get_container)) -> Response:
    payload = container.render_service.get_last_frame_png()
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No frame has been rendered yet.")
    return Response(content=payload, media_type="image/png")
