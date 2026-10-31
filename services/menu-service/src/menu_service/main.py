from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asyncpg.exceptions import PostgresError  # type: ignore[import-untyped]
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from menu_service.api.health import router
from menu_service.api.menu import router as business_router
from menu_service.config import Settings
from menu_service.infrastructure.database import Database
from menu_service.infrastructure.tokens import TokenVerifier


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = (
        Database(settings.database_url.get_secret_value(), settings.readiness_timeout_seconds)
        if settings.database_url
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = database
        try:
            yield
        finally:
            if database is not None:
                await database.close()

    app = FastAPI(
        title="MAI Food — Menu Service",
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

    app.include_router(router)
    app.include_router(business_router)
    return app
