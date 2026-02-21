from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.application.services import SetupRequest
from app.domain.value_objects import PetCommand
from app.presentation.dependencies import get_container

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))

router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


def _settings_context(
    container,
    hardware_result: dict | None = None,
) -> dict:
    current_profile = container.status_service.get_status()["state"].get("hardware_profile", "dummy")
    repo_root = container.config.built_in_plugin_directory.parent
    return {
        "app_name": container.config.app_name,
        "hardware_profiles": container.plugin_service.list_hardware_profiles(),
        "current_hardware_profile": current_profile,
        "hardware_result": hardware_result,
        "hardware_status": container.get_hardware_status(),
        "repo_root": str(repo_root),
    }


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

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": container.config.app_name,
            "capabilities": container.get_display_capabilities(),
            "frame_meta": container.get_display_frame_meta(),
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
    try:
        await container.plugin_service.enable(plugin_id)
    except Exception:
        logger.exception("Requested plugin could not be enabled.", extra={"plugin_id": plugin_id})
    current_state = container.status_service.get_status()["state"]
    container.refresh_display_driver(profile_id=current_state.get("hardware_profile", "dummy"))
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/{plugin_id}/disable")
async def plugins_disable(plugin_id: str, container=Depends(get_container)) -> RedirectResponse:
    try:
        await container.plugin_service.disable(plugin_id)
    except Exception:
        logger.exception("Requested plugin could not be disabled.", extra={"plugin_id": plugin_id})
    current_state = container.status_service.get_status()["state"]
    container.refresh_display_driver(profile_id=current_state.get("hardware_profile", "dummy"))
    return RedirectResponse(url="/plugins", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plugins/hardware-profile")
async def plugins_set_hardware_profile(
    container=Depends(get_container),
    hardware_profile: str = Form(...),
) -> RedirectResponse:
    try:
        await container.plugin_service.activate_hardware_profile(hardware_profile)
    except Exception:
        logger.exception("Requested hardware profile could not be activated.", extra={"hardware_profile": hardware_profile})
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
        context=_settings_context(
            container=container,
        ),
    )


@router.post("/settings/hardware")
async def settings_hardware_update(
    request: Request,
    container=Depends(get_container),
    hardware_profile: str = Form(...),
):
    hardware_result: dict
    try:
        await container.plugin_service.activate_hardware_profile(hardware_profile)
        status_payload = container.refresh_display_driver(profile_id=hardware_profile)
        message = str(status_payload.get("message", "Hardware backend update completed."))
        has_multiline_details = "\n" in message
        hardware_result = {
            "ok": status_payload.get("ok", False),
            "summary": (
                "Hardware backend update failed."
                if has_multiline_details and not status_payload.get("ok", False)
                else message
            ),
            "details": message if has_multiline_details else "",
        }
    except Exception as exc:
        hardware_result = {
            "ok": False,
            "summary": "Hardware backend update failed.",
            "details": str(exc),
        }

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_settings_context(
            container=container,
            hardware_result=hardware_result,
        ),
    )


@router.get("/debug/frame")
async def debug_frame(container=Depends(get_container)) -> Response:
    payload = container.get_display_frame_png()
    return Response(content=payload, media_type="image/png")
