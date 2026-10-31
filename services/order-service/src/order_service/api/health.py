import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from order_service.infrastructure.database import Database

logger = logging.getLogger(__name__)

SERVICE = "order-service"
router = APIRouter(prefix="/health", tags=["health"])


class Health(BaseModel):
    service: str
    status: str


@router.get("/live", response_model=Health)
async def live() -> Health:
    return Health(service=SERVICE, status="alive")


@router.get("/ready", response_model=Health)
async def ready(request: Request) -> Health | JSONResponse:
    database: Database | None = request.app.state.database
    if database is None:
        return JSONResponse(status_code=503, content={"service": SERVICE, "status": "not_ready"})
    try:
        async with asyncio.timeout(request.app.state.settings.readiness_timeout_seconds):
            await database.check_ready()
    except Exception:
        logger.warning("Database readiness check failed")
        return JSONResponse(status_code=503, content={"service": SERVICE, "status": "not_ready"})
    return Health(service=SERVICE, status="ready")
