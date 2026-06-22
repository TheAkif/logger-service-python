import asyncio
import os
from pathlib import Path

# Must be set before any app module is imported so settings.py reads these values.
os.environ.setdefault("DATABASE_URL", "postgresql://lis:lis@localhost:5433/lis_test")
os.environ.setdefault("INGEST_TOKEN", "test-token")
os.environ.setdefault("BATCH_FLUSH_SEC", "0.1")
os.environ.setdefault("ENV", "dev")

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import db  # noqa: E402
from app.batcher import Batcher  # noqa: E402
from app.main import app  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
_TEST_DB_URL = os.environ["DATABASE_URL"]


# ── Session-scoped sync fixtures ──────────────────────────────────────────────
# Keeping these synchronous avoids any event-loop scope mismatch: they each
# spin up a temporary loop via asyncio.run(), which is destroyed before any
# async test function starts its own loop.

@pytest.fixture(scope="session")
def db_setup():
    """Create the test database and run all migrations once per session."""
    async def _setup():
        db_name = _TEST_DB_URL.rsplit("/", 1)[-1]
        admin_url = _TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"

        conn = await asyncpg.connect(admin_url)
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        await conn.close()

        conn = await asyncpg.connect(_TEST_DB_URL)
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            await conn.execute(sql_file.read_text())
        await conn.close()

    asyncio.run(_setup())


@pytest.fixture(autouse=True)
def truncate_tables(db_setup):
    """Wipe all data tables before each test for full isolation."""
    async def _truncate():
        conn = await asyncpg.connect(_TEST_DB_URL)
        await conn.execute(
            "TRUNCATE log_events, failed_batches RESTART IDENTITY CASCADE"
        )
        await conn.close()

    asyncio.run(_truncate())


# ── Function-scoped async fixtures ────────────────────────────────────────────
# Everything here - the batcher task, the route handler, and the test function
# - runs in the SAME function-scoped event loop, so asyncio tasks scheduled in
# the batcher are visible to awaits in the test body.

@pytest.fixture
async def async_client(db_setup):
    """
    Full app stack: DB pool + batcher task running.

    ASGITransport does not trigger FastAPI's lifespan, so we manage the
    DB pool and batcher lifecycle manually.
    """
    await db.connect()
    _batcher = Batcher()
    await _batcher.start()

    import app.main as _main
    _main.batcher = _batcher

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        try:
            await asyncio.wait_for(_batcher.stop(), timeout=10)
        except asyncio.TimeoutError:
            pass
        await db.disconnect()


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def sample_log() -> dict:
    return {
        "tenantId": "test-tenant",
        "source": "test-service",
        "environment": "dev",
        "level": "info",
        "type": "app",
        "message": "hello from test",
    }
