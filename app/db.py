import asyncpg
from .settings import DATABASE_URL

pool: asyncpg.Pool | None = None

async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

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
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("SELECT 1")
