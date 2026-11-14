from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

SERVICE = "websocket-service"
router = APIRouter(prefix="/health", tags=["health"])


class Health(BaseModel):
    service: str
    status: str


@router.get("/live", response_model=Health)
async def live() -> Health:
    return Health(service=SERVICE, status="alive")


@router.get("/ready", response_model=Health)
async def ready(request: Request) -> Health:
    if not request.app.state.hub.ready:
        raise HTTPException(503, "Kitchen event stream unavailable")
    return Health(service=SERVICE, status="ready")
