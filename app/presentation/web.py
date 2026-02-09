from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.application.services import SetupRequest
from app.domain.value_objects import PetCommand
from app.presentation.dependencies import get_container

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
PROJECT_ROOT = TEMPLATE_DIRECTORY.parent.parent.parent
UPDATE_SCRIPT_PATH = Path(os.getenv("CLWG_UPDATE_SCRIPT", str(PROJECT_ROOT / "update.sh")))
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
    hardware_profiles = container.plugin_service.list_hardware_profiles()
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "app_name": container.config.app_name,
            "themes": themes,
            "plugins": plugins,
            "hardware_profiles": hardware_profiles,
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
    container.refresh_display_driver(profile_id=hardware_profile)
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
    hardware_profiles = container.plugin_service.list_hardware_profiles()
    current_profile = container.status_service.get_status()["state"].get("hardware_profile", "dummy")
    return templates.TemplateResponse(
        request=request,
        name="plugins.html",
        context={
            "app_name": container.config.app_name,
            "plugins": plugins,
            "hardware_profiles": hardware_profiles,
            "current_profile": current_profile,
        },
    )


@router.post("/plugins/rescan")
async def plugins_rescan(container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.rescan()
    current_state = container.status_service.get_status()["state"]
    container.refresh_display_driver(profile_id=current_state.get("hardware_profile", "dummy"))
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/{plugin_id}/enable")
async def plugins_enable(plugin_id: str, container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.enable(plugin_id)
    current_state = container.status_service.get_status()["state"]
    container.refresh_display_driver(profile_id=current_state.get("hardware_profile", "dummy"))
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/{plugin_id}/disable")
async def plugins_disable(plugin_id: str, container=Depends(get_container)) -> RedirectResponse:
    await container.plugin_service.disable(plugin_id)
    current_state = container.status_service.get_status()["state"]
    container.refresh_display_driver(profile_id=current_state.get("hardware_profile", "dummy"))
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/hardware-profile")
async def plugins_set_hardware_profile(
    container=Depends(get_container),
    hardware_profile: str = Form(...),
) -> RedirectResponse:
    container.plugin_service.set_hardware_profile(hardware_profile)
    container.refresh_display_driver(profile_id=hardware_profile)
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


@router.get("/settings")
async def settings_page(request: Request, container=Depends(get_container)):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name": container.config.app_name,
            "update_script_path": str(UPDATE_SCRIPT_PATH),
            "update_result": None,
        },
    )


@router.post("/settings/update")
async def settings_update(request: Request, container=Depends(get_container)):
    if not UPDATE_SCRIPT_PATH.exists():
        result = {
            "ok": False,
            "summary": f"Update script wurde nicht gefunden: {UPDATE_SCRIPT_PATH}",
            "stdout": "",
            "stderr": "",
        }
    elif not os.access(UPDATE_SCRIPT_PATH, os.X_OK):
        result = {
            "ok": False,
            "summary": f"Update script ist nicht ausfuehrbar: {UPDATE_SCRIPT_PATH}",
            "stdout": "",
            "stderr": "",
        }
    else:
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [str(UPDATE_SCRIPT_PATH)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
            result = {
                "ok": completed.returncode == 0,
                "summary": (
                    "Update erfolgreich abgeschlossen."
                    if completed.returncode == 0
                    else f"Update fehlgeschlagen (exit={completed.returncode})."
                ),
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            result = {
                "ok": False,
                "summary": "Update wurde nach 600 Sekunden abgebrochen (Timeout).",
                "stdout": "",
                "stderr": "",
            }

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name": container.config.app_name,
            "update_script_path": str(UPDATE_SCRIPT_PATH),
            "update_result": result,
        },
    )


@router.get("/debug/frame")
async def debug_frame(container=Depends(get_container)) -> Response:
    payload = container.render_service.get_last_frame_png()
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No frame has been rendered yet.")
    return Response(content=payload, media_type="image/png")
