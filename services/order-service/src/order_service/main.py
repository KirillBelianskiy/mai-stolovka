from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asyncpg.exceptions import PostgresError  # type: ignore[import-untyped]
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from order_service.api.health import router
from order_service.api.orders import router as business_router
from order_service.api.slots import router as slots_router
from order_service.api.wallet import router as wallet_router
from order_service.config import Settings
from order_service.domain.orders import OrderError
from order_service.infrastructure.database import Database
from order_service.infrastructure.menu import MenuClient
from order_service.infrastructure.tokens import TokenVerifier


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = (
        Database(settings.database_url.get_secret_value(), settings.readiness_timeout_seconds)
        if settings.database_url
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        menu = MenuClient(settings)
        app.state.database = database
        app.state.menu = menu
        try:
            yield
        finally:
            await menu.close()
            if database is not None:
                await database.close()

    app = FastAPI(
        title="MAI Food — Order Service",
        lifespan=lifespan,
        servers=[{"url": settings.root_path}],
    )
    app.state.tokens = TokenVerifier(settings)
    app.state.settings = settings

    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(PostgresError)
    @app.exception_handler(OSError)
    @app.exception_handler(TimeoutError)
    async def database_error(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database is unavailable"})

    @app.exception_handler(OrderError)
    async def order_error(request: Request, error: OrderError) -> JSONResponse:
        headers = {"Retry-After": "1"} if error.status == 503 else None
        return JSONResponse(
            status_code=error.status, content={"detail": error.detail}, headers=headers
        )

    app.include_router(slots_router)
    app.include_router(router)
    app.include_router(wallet_router)
    app.include_router(business_router)
    return app
