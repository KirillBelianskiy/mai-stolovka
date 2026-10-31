from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str, timeout: float) -> None:
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=timeout,
            connect_args={
                "timeout": timeout,
                "command_timeout": timeout,
                "server_settings": {"application_name": "user-service"},
            },
        )
        self.sessions = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def check_ready(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
