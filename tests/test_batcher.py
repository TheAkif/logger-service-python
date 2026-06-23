import asyncio
import os
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from httpx import AsyncClient

import app.main as _main

_DB_URL = os.environ["DATABASE_URL"]


async def _count_logs() -> int:
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM log_events")
    finally:
        await conn.close()


async def _count_dead_letters() -> int:
    conn = await asyncpg.connect(_DB_URL)
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM failed_batches")
    finally:
        await conn.close()


# ── events land in DB after flush ────────────────────────────────────────────

async def test_enqueued_event_lands_in_db(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 202

    # BATCH_FLUSH_SEC=0.1 in test env; give the batcher two cycles to flush
    await asyncio.sleep(0.4)

    assert await _count_logs() == 1


async def test_batch_post_all_land_in_db(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    events = [sample_log] * 10
    resp = await async_client.post("/v1/logs/batch", json=events, headers=auth_headers)
    assert resp.status_code == 202

    await asyncio.sleep(0.4)

    assert await _count_logs() == 10


# ── dead-letter on flush error ────────────────────────────────────────────────

async def test_flush_error_writes_to_dead_letter(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    import app.main as main_module

    # Hold the mock active from the moment of POST so the background flush
    # task can't beat us to writing the event successfully.
    with patch("app.repo.insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.side_effect = Exception("simulated DB failure")
        resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
        assert resp.status_code == 202
        # Explicitly flush so we don't have to race the background task.
        await main_module.batcher.flush_now()

    assert await _count_logs() == 0
    assert await _count_dead_letters() == 1


async def test_flush_error_does_not_raise(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    import app.main as main_module

    with patch("app.repo.insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.side_effect = Exception("simulated DB failure")
        await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
        # Must not raise - flush errors are handled internally
        await main_module.batcher.flush_now()

    assert main_module.batcher.flush_errors >= 1


# ── batcher stats endpoint ────────────────────────────────────────────────────

async def test_batcher_stats_endpoint(async_client: AsyncClient):
    resp = await async_client.get("/internal/health")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("enqueued", "flushed", "dropped", "flush_errors", "queued", "uptime_sec", "last_flush_at"):
        assert key in data
