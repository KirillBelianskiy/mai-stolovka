"""Explicit, single-worker READY delivery process."""

import argparse
import asyncio
import logging
import signal
from re import fullmatch

import httpx
from pydantic import AnyHttpUrl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from notification_service.application.delivery import dispatch_once
from notification_service.config import Settings
from notification_service.domain.delivery import NETWORK_TIMEOUT
from notification_service.infrastructure.delivery_http import BotClient, ServiceTokens, UserClient
from notification_service.infrastructure.dispatch import DispatchStore

logger = logging.getLogger("notification-dispatch")
WORKER_LOCK = 2107268304704808352


def origin(url: AnyHttpUrl | None) -> str:
    if (
        url is None
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in (None, "", "/")
    ):
        raise ValueError("invalid_dispatch_origin")
    return str(url)


def bot_endpoint(settings: Settings) -> tuple[str, str]:
    if settings.dispatch_bot_mode == "fake" and settings.dispatch_bot_token is None:
        url = origin(settings.dispatch_fake_bot_url)
        fake = settings.dispatch_fake_bot_url
        if fake is not None and fake.host != "api.telegram.org":
            return url, "0:fake-test-token"
    if (
        settings.dispatch_bot_mode == "telegram"
        and settings.dispatch_fake_bot_url is None
        and settings.dispatch_bot_token is not None
    ):
        token = settings.dispatch_bot_token.get_secret_value()
        if fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            return "https://api.telegram.org", token
    raise ValueError("invalid_dispatch_bot_configuration")


async def run(check: bool) -> None:
    settings = Settings()
    if settings.dispatch_bot_mode == "disabled":
        if check:
            raise RuntimeError("dispatch_disabled")
        logger.info("dispatch_disabled")
        return
    if settings.database_url is None:
        raise ValueError("dispatch_database_required")

    user_url = origin(settings.dispatch_user_url)
    bot_url, bot_token = bot_endpoint(settings)
    tokens = ServiceTokens(settings)
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={"timeout": 5, "command_timeout": 5},
    )
    try:
        async with engine.connect() as guard:
            if not await guard.scalar(text("SELECT id FROM dispatch_bot WHERE id = 1")):
                raise RuntimeError("dispatch_schema_unavailable")
            if check:
                return
            if not await guard.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}
            ):
                raise RuntimeError("dispatch_worker_already_running")
            await guard.commit()
            # Keep the original session for the lifetime of the worker.
            loop = asyncio.get_running_loop()
            stop = asyncio.Event()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)

            async with (
                httpx.AsyncClient(
                    base_url=user_url,
                    timeout=NETWORK_TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                ) as user_http,
                httpx.AsyncClient(
                    base_url=bot_url,
                    timeout=NETWORK_TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                ) as bot_http,
            ):
                user, bot = UserClient(user_http, tokens), BotClient(bot_http, bot_token)
                store = DispatchStore(async_sessionmaker(engine, expire_on_commit=False))
                logger.info("dispatch_started mode=%s", settings.dispatch_bot_mode)
                while not stop.is_set():
                    async with guard.begin():
                        held = await guard.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks "
                                "WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted "
                                "AND classid=:high AND objid=:low AND objsubid=1)"
                            ),
                            {"high": WORKER_LOCK >> 32, "low": WORKER_LOCK & 0xFFFFFFFF},
                        )
                        if not held:
                            raise RuntimeError("dispatch_guard_lost")
                    if not await dispatch_once(store, user, bot):
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1)
                        except TimeoutError:
                            continue
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check config and dispatch database.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # HTTP request URLs can contain the bot token. Never emit library traffic logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    try:
        asyncio.run(run(args.check))
    except Exception as error:
        logger.error("dispatch_stopped error_class=%s", type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
