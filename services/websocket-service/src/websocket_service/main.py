import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from websocket_service.api.health import router
from websocket_service.api.websocket import router as websocket_router
from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings
from websocket_service.infrastructure.kafka import run_consumer
from websocket_service.infrastructure.tokens import TokenVerifier


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker = None
        if settings.kitchen_kafka_enabled:
            worker = asyncio.create_task(run_consumer(settings, app.state.hub))
        try:
            yield
        finally:
            await app.state.hub.shutdown()
            if worker is not None:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app = FastAPI(title="MAI Food — Websocket Service", lifespan=lifespan)
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(settings)
    app.state.hub = KitchenHub(
        settings.websocket_queue_size, ready=not settings.kitchen_kafka_enabled
    )
    app.include_router(router)
    app.include_router(websocket_router)
    return app
