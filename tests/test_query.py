import os
from datetime import datetime, timezone, timedelta

import asyncpg
import pytest
from httpx import AsyncClient

from app.models import LogEvent
from app import repo

_DB_URL = os.environ["DATABASE_URL"]

_BASE = {
    "tenantId": "tenant-a",
    "source": "auth-service",
    "environment": "dev",
    "level": "info",
    "type": "app",
    "message": "baseline event",
}


def _event(**overrides) -> LogEvent:
    return LogEvent(**{**_BASE, **overrides})


# ── tenant filter ─────────────────────────────────────────────────────────────

async def test_query_by_tenant(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event() for _ in range(10)])
    await repo.insert_batch([_event(tenantId="tenant-b") for _ in range(5)])

    resp = await async_client.get("/v1/logs", params={"tenant_id": "tenant-a"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 10
    assert len(data["items"]) == 10
    assert all(item["tenantId"] == "tenant-a" for item in data["items"])


# ── level filter ──────────────────────────────────────────────────────────────

async def test_query_by_level(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event(level="error") for _ in range(3)])
    await repo.insert_batch([_event(level="info") for _ in range(7)])

    resp = await async_client.get("/v1/logs", params={"level": "error"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert all(item["level"] == "error" for item in data["items"])


# ── source filter ─────────────────────────────────────────────────────────────

async def test_query_by_source(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event(source="api-gateway") for _ in range(4)])
    await repo.insert_batch([_event(source="worker") for _ in range(6)])

    resp = await async_client.get("/v1/logs", params={"source": "api-gateway"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


# ── time range filter ─────────────────────────────────────────────────────────

async def test_query_time_range(async_client: AsyncClient, auth_headers: dict):
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)

    await repo.insert_batch([_event(occurredAt=now)])
    await repo.insert_batch([_event(occurredAt=yesterday)])
    await repo.insert_batch([_event(occurredAt=last_week)])

    resp = await async_client.get(
        "/v1/logs",
        params={"from_dt": (now - timedelta(hours=1)).isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ── full-text search ──────────────────────────────────────────────────────────

async def test_query_fulltext(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event(message="Login failed invalid password")])
    await repo.insert_batch([_event(message="User session created")])
    await repo.insert_batch([_event(message="Login failed rate limit exceeded")])

    resp = await async_client.get("/v1/logs", params={"q": "login failed"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# ── pagination ────────────────────────────────────────────────────────────────

async def test_query_pagination(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event() for _ in range(15)])

    page1 = await async_client.get(
        "/v1/logs", params={"limit": 5, "page": 1}, headers=auth_headers
    )
    assert page1.status_code == 200
    d1 = page1.json()
    assert d1["total"] == 15
    assert len(d1["items"]) == 5

    page2 = await async_client.get(
        "/v1/logs", params={"limit": 5, "page": 2}, headers=auth_headers
    )
    assert page2.status_code == 200
    d2 = page2.json()
    assert len(d2["items"]) == 5

    ids_page1 = {item["id"] for item in d1["items"]}
    ids_page2 = {item["id"] for item in d2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


# ── get by ID ─────────────────────────────────────────────────────────────────

async def test_get_log_by_id(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([_event(message="unique marker event")])

    list_resp = await async_client.get(
        "/v1/logs", params={"q": "marker"}, headers=auth_headers
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    log_id = items[0]["id"]

    get_resp = await async_client.get(f"/v1/logs/{log_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == log_id
    assert get_resp.json()["message"] == "unique marker event"


async def test_get_log_not_found(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get(
        "/v1/logs/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert resp.status_code == 404


# ── auth ──────────────────────────────────────────────────────────────────────

async def test_query_requires_auth(async_client: AsyncClient):
    resp = await async_client.get("/v1/logs")
    assert resp.status_code == 403
