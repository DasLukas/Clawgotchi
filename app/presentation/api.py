from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.domain.value_objects import PetCommand
from app.presentation.dependencies import get_container, require_api_key
from app.presentation.schemas import CommandRequest, CommandResponse, ExportStateResponse, ImportStateRequest

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/status", dependencies=[Depends(require_api_key)])
async def get_status(container=Depends(get_container)) -> dict:
    return container.status_service.get_status()


@router.post(
    "/commands",
    response_model=CommandResponse,
    dependencies=[Depends(require_api_key)],
)
async def post_command(payload: CommandRequest, container=Depends(get_container)) -> CommandResponse:
    try:
        command = PetCommand(type=payload.type, intensity=payload.intensity, source=payload.source)
        result = await container.send_command_service.send(command)
        return CommandResponse(
            accepted=result.accepted,
            command_id=result.command_id,
            state_version=result.state_version,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Command processing timed out.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/state/export", response_model=ExportStateResponse, dependencies=[Depends(require_api_key)])
async def export_state(container=Depends(get_container)) -> ExportStateResponse:
    snapshot = await container.state_transfer_service.export_state()
    return ExportStateResponse(**snapshot)


@router.post("/state/import", dependencies=[Depends(require_api_key)])
async def import_state(payload: ImportStateRequest, container=Depends(get_container)) -> JSONResponse:
    try:
        result = await container.state_transfer_service.import_state(
            payload=payload.snapshot,
            dry_run=payload.dry_run,
        )
        return JSONResponse(content=result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/plugins", dependencies=[Depends(require_api_key)])
async def list_plugins(container=Depends(get_container)) -> list[dict]:
    return container.plugin_service.list_plugins()


@router.get("/themes", dependencies=[Depends(require_api_key)])
async def list_themes(container=Depends(get_container)) -> list[dict]:
    return container.theme_service.list_themes()
