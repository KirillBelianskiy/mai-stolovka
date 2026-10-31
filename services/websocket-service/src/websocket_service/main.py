from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from websocket_service.api.health import router
from websocket_service.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(title="MAI Food — Websocket Service", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)
    return app
