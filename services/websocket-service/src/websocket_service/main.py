from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from websocket_service.api.health import router
from websocket_service.api.websocket import router as websocket_router
from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings
from websocket_service.infrastructure.tokens import TokenVerifier


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await app.state.hub.shutdown()

    app = FastAPI(title="MAI Food — Websocket Service", lifespan=lifespan)
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(settings)
    app.state.hub = KitchenHub(settings.websocket_queue_size)
    app.include_router(router)
    app.include_router(websocket_router)
    return app
