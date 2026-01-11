import asyncpg
from .settings import (
    DATABASE_URL,
    DB_POOL_MIN,
    DB_POOL_MAX,
    DB_COMMAND_TIMEOUT,
    DB_ACQUIRE_TIMEOUT,
)

pool: asyncpg.Pool | None = None


async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=DB_POOL_MIN,
        max_size=DB_POOL_MAX,
        # closes idle connections so the pool doesn't keep stale ones forever
        max_inactive_connection_lifetime=60,
        # default statement timeout (seconds) for queries on connections from this pool
        command_timeout=DB_COMMAND_TIMEOUT,
    )


async def disconnect() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("DB pool is not initialized")
    return pool


async def ping() -> None:
    """
    Lightweight readiness probe. Acquires a connection and executes SELECT 1.
    """
    p = get_pool()
    async with p.acquire(timeout=DB_ACQUIRE_TIMEOUT) as conn:
        await conn.execute("SELECT 1")
