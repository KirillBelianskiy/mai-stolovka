from fastapi import APIRouter
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
async def ready() -> Health:
    """Report process readiness only; no worker or integration is running yet."""
    return Health(service=SERVICE, status="ready")
