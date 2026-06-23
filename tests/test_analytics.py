from datetime import datetime, timezone, timedelta

import pytest
from httpx import AsyncClient

from app.models import LogEvent
from app import repo

_TENANT = "analytics-tenant"

_BASE = {
    "tenantId": _TENANT,
    "source": "svc-a",
    "environment": "dev",
    "level": "info",
    "type": "app",
    "message": "analytics test event",
}


def _event(**overrides) -> LogEvent:
    return LogEvent(**{**_BASE, **overrides})


# ── summary ───────────────────────────────────────────────────────────────────

async def test_summary_counts(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch([
        _event(level="error"),
        _event(level="error"),
        _event(level="warn"),
        _event(level="info"),
        _event(level="info"),
        _event(level="info"),
        _event(type="access", level="debug"),   # distinct level to isolate type counts
        _event(type="audit", level="debug"),    # distinct level to isolate type counts
        _event(source="svc-b", level="fatal"),  # distinct level to isolate source counts
        _event(source="svc-b", level="fatal"),  # distinct level to isolate source counts
    ])

    resp = await async_client.get(
        "/v1/analytics/summary", params={"tenant_id": _TENANT}, headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["by_level"]["error"] == 2
    assert data["by_level"]["warn"] == 1
    assert data["by_level"]["info"] == 3
    assert data["by_level"]["debug"] == 2
    assert data["by_level"]["fatal"] == 2
    assert data["by_type"]["app"] == 8
    assert data["by_type"]["access"] == 1
    assert data["by_type"]["audit"] == 1
    assert data["by_source"]["svc-b"] == 2


async def test_summary_requires_tenant(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get("/v1/analytics/summary", headers=auth_headers)
    assert resp.status_code == 422


# ── timeline ──────────────────────────────────────────────────────────────────

async def test_timeline_buckets(async_client: AsyncClient, auth_headers: dict):
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)

    await repo.insert_batch([
        _event(occurredAt=now),
        _event(occurredAt=now),
        _event(occurredAt=two_hours_ago),
    ])

    resp = await async_client.get(
        "/v1/analytics/timeline",
        params={"tenant_id": _TENANT, "interval": "hour"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    buckets = resp.json()
    assert len(buckets) == 2
    counts = sorted([b["count"] for b in buckets])
    assert counts == [1, 2]


async def test_timeline_invalid_interval(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get(
        "/v1/analytics/timeline",
        params={"tenant_id": _TENANT, "interval": "minute"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── top sources ───────────────────────────────────────────────────────────────

async def test_top_sources_order(async_client: AsyncClient, auth_headers: dict):
    await repo.insert_batch(
        [_event(source="svc-a")] * 5
        + [_event(source="svc-b")] * 3
        + [_event(source="svc-c")] * 1
    )

    resp = await async_client.get(
        "/v1/analytics/top-sources",
        params={"tenant_id": _TENANT, "n": 3},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    sources = resp.json()
    assert sources[0]["source"] == "svc-a"
    assert sources[0]["count"] == 5
    assert sources[1]["source"] == "svc-b"
    assert sources[1]["count"] == 3
    assert sources[2]["source"] == "svc-c"
    assert sources[2]["count"] == 1


# ── error rate ────────────────────────────────────────────────────────────────

async def test_error_rate(async_client: AsyncClient, auth_headers: dict):
    now = datetime.now(timezone.utc)
    await repo.insert_batch([
        _event(level="info", occurredAt=now),
        _event(level="info", occurredAt=now),
        _event(level="error", occurredAt=now),
        _event(level="fatal", occurredAt=now),
    ])

    resp = await async_client.get(
        "/v1/analytics/error-rate",
        params={"tenant_id": _TENANT},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    buckets = resp.json()
    assert len(buckets) == 1
    b = buckets[0]
    assert b["total"] == 4
    assert b["errors"] == 2
    assert b["error_rate_pct"] == 50.0
