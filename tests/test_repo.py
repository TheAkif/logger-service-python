import json
import os

import asyncpg
import pytest

from app import repo
from app.models import Environment, LogEvent, LogLevel, LogType

_DB_URL = os.environ["DATABASE_URL"]


def _make_event(**kwargs) -> LogEvent:
    defaults = dict(
        tenantId="repo-test",
        source="test-service",
        environment=Environment.dev,
        level=LogLevel.info,
        type=LogType.app,
        message="repo test event",
    )
    defaults.update(kwargs)
    return LogEvent(**defaults)


async def _count_logs() -> int:
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM log_events")
    finally:
        await conn.close()


# ── insert_batch happy path ───────────────────────────────────────────────────

async def test_insert_batch_persists_rows(async_client):
    events = [_make_event(message=f"msg {i}") for i in range(5)]
    await repo.insert_batch(events)
    assert await _count_logs() == 5


async def test_insert_one_persists_row(async_client):
    event = _make_event(message="single insert")
    await repo.insert_one(event)
    assert await _count_logs() == 1


# ── atomicity: DB-level transaction rollback guarantee ────────────────────────

async def test_transaction_rolls_back_on_error(async_client):
    """asyncpg transactions roll back when an exception fires inside them.
    This is the DB-level guarantee that our conn.transaction() wrapper in
    insert_batch() relies on."""
    conn = await asyncpg.connect(_DB_URL)
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO log_events "
                "(occurred_at, tenant_id, source, environment, level, type, message) "
                "VALUES (now(), 'tx-test', 'svc', 'dev', 'info', 'app', 'will be rolled back')"
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    count = await conn.fetchval("SELECT COUNT(*) FROM log_events")
    await conn.close()
    assert count == 0


# ── insert_batch edge cases ───────────────────────────────────────────────────

async def test_insert_batch_empty_list_is_noop(async_client):
    await repo.insert_batch([])
    assert await _count_logs() == 0


async def test_insert_batch_optional_fields_nullable(async_client):
    event = _make_event()
    assert event.traceId is None
    assert event.properties is None
    await repo.insert_batch([event])

    conn = await asyncpg.connect(_DB_URL)
    try:
        row = await conn.fetchrow("SELECT * FROM log_events")
        assert row["trace_id"] is None
        assert row["properties"] is None
    finally:
        await conn.close()


async def test_insert_batch_with_all_fields(async_client):
    event = _make_event(
        traceId="trace-abc",
        spanId="span-xyz",
        correlationId="corr-1",
        requestId="req-1",
        userId="user-42",
        path="/api/v1/test",
        method="GET",
        statusCode=200,
        durationMs=45,
        exception={"name": "ValueError", "message": "oops"},
        properties={"key": "value"},
    )
    await repo.insert_batch([event])

    conn = await asyncpg.connect(_DB_URL)
    try:
        row = await conn.fetchrow("SELECT * FROM log_events")
        assert row["trace_id"] == "trace-abc"
        assert row["user_id"] == "user-42"
        assert row["status_code"] == 200
        # asyncpg returns JSONB columns as JSON strings without a registered codec
        assert json.loads(row["properties"]) == {"key": "value"}
    finally:
        await conn.close()
