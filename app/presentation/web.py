from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.application.services import SetupRequest
from app.domain.value_objects import PetCommand
from app.presentation.dependencies import get_container

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
PROJECT_ROOT = TEMPLATE_DIRECTORY.parent.parent.parent
UPDATE_SCRIPT_PATH = Path(os.getenv("CLWG_UPDATE_SCRIPT", str(PROJECT_ROOT / "update.sh")))
UPDATE_SERVICE_NAME = os.getenv("CLWG_UPDATE_SERVICE_NAME", "clawgotchi-update.service")
UPDATE_STATUS_FILE = Path(os.getenv("CLWG_UPDATE_STATUS_FILE", "/tmp/clawgotchi-update-status.env"))
UPDATE_SCRIPT_TIMEOUT_SECONDS = int(os.getenv("CLWG_UPDATE_TIMEOUT_SECONDS", "600"))
UPDATE_SERVICE_START_TIMEOUT_SECONDS = int(os.getenv("CLWG_UPDATE_START_TIMEOUT_SECONDS", "30"))
UPDATE_SERVICE_STATUS_TIMEOUT_SECONDS = int(os.getenv("CLWG_UPDATE_STATUS_TIMEOUT_SECONDS", "5"))
templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))

router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


def _settings_context(
    container,
    update_result: dict | None = None,
    hardware_result: dict | None = None,
    update_status: dict | None = None,
) -> dict:
    current_profile = container.status_service.get_status()["state"].get("hardware_profile", "dummy")
    return {
        "app_name": container.config.app_name,
        "update_script_path": str(UPDATE_SCRIPT_PATH),
        "update_result": update_result,
        "update_status": update_status,
        "hardware_profiles": container.plugin_service.list_hardware_profiles(),
        "current_hardware_profile": current_profile,
        "hardware_result": hardware_result,
        "hardware_status": container.get_hardware_status(),
        "update_async_available": _is_async_update_available(),
        "update_status_endpoint": "/settings/update/status",
        "update_start_endpoint": "/settings/update/start",
        "update_fallback_endpoint": "/settings/update",
    }


def _is_async_update_available() -> bool:
    return shutil.which("systemctl") is not None


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_key_value_payload(payload: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in payload.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip()
    return parsed


def _read_status_file_payload() -> dict[str, str]:
    if not UPDATE_STATUS_FILE.exists():
        return {}
    try:
        content = UPDATE_STATUS_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_key_value_payload(content)


def _read_systemd_update_state() -> dict[str, str] | None:
    if shutil.which("systemctl") is None:
        return None
    try:
        completed = subprocess.run(
            [
                "systemctl",
                "show",
                UPDATE_SERVICE_NAME,
                "--property=ActiveState,SubState,Result",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=UPDATE_SERVICE_STATUS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"error": "Unable to query systemd update service state."}

    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or f"exit={completed.returncode}"
        return {"error": details}

    return _parse_key_value_payload(completed.stdout)


def _build_update_status_payload() -> dict:
    status_file_payload = _read_status_file_payload()
    state = status_file_payload.get("state", "idle")
    message = status_file_payload.get("message", "No update has been started yet.")
    running = state in {"starting", "running", "rebooting"}

    service_state = _read_systemd_update_state()
    service_error = ""
    service_details: dict[str, str] = {}
    if service_state is not None:
        if "error" in service_state:
            service_error = service_state["error"]
        else:
            service_details = {
                "active_state": service_state.get("ActiveState", ""),
                "sub_state": service_state.get("SubState", ""),
                "result": service_state.get("Result", ""),
            }
            if service_details["active_state"] in {"active", "activating", "reloading", "deactivating"}:
                running = True
                if state in {"idle", "succeeded", "failed"}:
                    state = "running"
                    message = "Update is running."
            elif state == "idle" and service_details["result"] and service_details["result"] != "success":
                state = "failed"
                message = f"Update service reported '{service_details['result']}'."

    if not status_file_payload and not service_details:
        message = "No update status available yet."

    return {
        "state": state,
        "running": running,
        "message": message,
        "started_at": status_file_payload.get("started_at", ""),
        "updated_at": status_file_payload.get("updated_at", ""),
        "reboot_required": _parse_bool(status_file_payload.get("reboot_required")),
        "reboot_scheduled": _parse_bool(status_file_payload.get("reboot_scheduled")),
        "exit_code": status_file_payload.get("exit_code", ""),
        "service": service_details,
        "service_error": service_error,
    }


def _start_update_service() -> tuple[bool, str]:
    if shutil.which("systemctl") is None:
        return False, "systemctl is not available on this host."

    command = (
        ["systemctl", "start", UPDATE_SERVICE_NAME]
        if os.geteuid() == 0
        else ["sudo", "-n", "systemctl", "start", UPDATE_SERVICE_NAME]
    )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=UPDATE_SERVICE_START_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, "Starting the update service timed out."
    except OSError as exc:
        return False, f"Unable to start update service: {exc}"

    if completed.returncode == 0:
        return True, f"Update service '{UPDATE_SERVICE_NAME}' started."

    details = completed.stderr.strip() or completed.stdout.strip() or f"exit={completed.returncode}"
    if os.geteuid() != 0:
        details = (
            f"{details} Configure sudoers to allow 'systemctl start {UPDATE_SERVICE_NAME}' "
            "without password prompts."
        )
    return False, f"Unable to start update service '{UPDATE_SERVICE_NAME}': {details}"


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
    update_status = await asyncio.to_thread(_build_update_status_payload)
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_settings_context(
            container=container,
            update_status=update_status,
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
            update_status=await asyncio.to_thread(_build_update_status_payload),
        ),
    )


@router.post("/settings/update/start")
async def settings_update_start():
    current_status = await asyncio.to_thread(_build_update_status_payload)
    if current_status.get("running", False):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "ok": False,
                "summary": "An update is already running.",
                "status": current_status,
            },
        )

    ok, summary = await asyncio.to_thread(_start_update_service)
    updated_status = await asyncio.to_thread(_build_update_status_payload)
    http_status = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=http_status,
        content={
            "ok": ok,
            "summary": summary,
            "status": updated_status,
        },
    )


@router.get("/settings/update/status")
async def settings_update_status():
    return JSONResponse(content=await asyncio.to_thread(_build_update_status_payload))


@router.post("/settings/update")
async def settings_update(request: Request, container=Depends(get_container)):
    if not UPDATE_SCRIPT_PATH.exists():
        result = {
            "ok": False,
            "summary": f"Update script was not found: {UPDATE_SCRIPT_PATH}",
            "stdout": "",
            "stderr": "",
        }
    elif not os.access(UPDATE_SCRIPT_PATH, os.X_OK):
        result = {
            "ok": False,
            "summary": f"Update script is not executable: {UPDATE_SCRIPT_PATH}",
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
                timeout=UPDATE_SCRIPT_TIMEOUT_SECONDS,
            )
            result = {
                "ok": completed.returncode == 0,
                "summary": (
                    "Update finished successfully."
                    if completed.returncode == 0
                    else f"Update failed (exit={completed.returncode})."
                ),
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            result = {
                "ok": False,
                "summary": f"Update timed out after {UPDATE_SCRIPT_TIMEOUT_SECONDS} seconds.",
                "stdout": "",
                "stderr": "",
            }

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_settings_context(
            container=container,
            update_result=result,
            update_status=await asyncio.to_thread(_build_update_status_payload),
        ),
    )


@router.get("/debug/frame")
async def debug_frame(container=Depends(get_container)) -> Response:
    payload = container.render_service.get_last_frame_png()
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No frame has been rendered yet.")
    return Response(content=payload, media_type="image/png")
