from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.domain.ui.input import ButtonId
from app.presentation.dependencies import get_container

router = APIRouter(tags=["input"])


class ButtonPressRequest(BaseModel):
    button: str


@router.post("/api/input/button")
async def post_input_button(payload: ButtonPressRequest, container=Depends(get_container)) -> dict[str, bool]:
    try:
        button = ButtonId(payload.button.strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported button id.") from exc

    container.publish_button_event(button)
    return {"ok": True}
