from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not available.")
    return container


async def require_api_key(request: Request, container: ApplicationContainer = Depends(get_container)) -> None:
    expected_key = container.config.api_key.strip()
    if not expected_key:
        return

    provided_key = request.headers.get("x-api-key", "")
    if provided_key != expected_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
