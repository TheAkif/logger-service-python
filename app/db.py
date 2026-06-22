import asyncio
import logging

import asyncpg

from .settings import (
    DATABASE_URL,
    DB_POOL_MIN,
    DB_POOL_MAX,
    DB_COMMAND_TIMEOUT,
    DB_ACQUIRE_TIMEOUT,
)

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None

_MAX_RETRIES = 5
_RETRY_BASE_SEC = 2.0


async def connect() -> None:
    global pool
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            pool = await asyncpg.create_pool(
                dsn=DATABASE_URL,
                min_size=DB_POOL_MIN,
                max_size=DB_POOL_MAX,
                max_inactive_connection_lifetime=60,
                command_timeout=DB_COMMAND_TIMEOUT,
            )
            logger.info("db_connected", extra={"attempt": attempt})
            return
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                logger.error("db_connect_failed", extra={"attempts": attempt, "error": str(exc)})
                raise
            wait = _RETRY_BASE_SEC * (2 ** (attempt - 1))
            logger.warning(
                "db_connect_retry",
                extra={"attempt": attempt, "wait_sec": wait, "error": str(exc)},
            )
            await asyncio.sleep(wait)


async def disconnect() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        logger.info("db_disconnected")


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("DB pool is not initialized")
    return pool


async def ping() -> None:
    p = get_pool()
    async with p.acquire(timeout=DB_ACQUIRE_TIMEOUT) as conn:
        await conn.execute("SELECT 1")
