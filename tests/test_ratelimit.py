import pytest
from httpx import AsyncClient

_ADMIN = {"Authorization": "Bearer test-token"}

_SAMPLE = {
    "tenantId": "rl-tenant",
    "source": "svc",
    "environment": "dev",
    "level": "info",
    "type": "app",
    "message": "rate limit test",
}


async def _setup(client: AsyncClient, limit: int) -> str:
    await client.post(
        "/admin/tenants",
        json={"id": "rl-tenant", "name": "RL Tenant"},
        headers=_ADMIN,
    )
    await client.put(
        "/admin/tenants/rl-tenant/config",
        json={"config": {"rate_limit_per_min": limit}},
        headers=_ADMIN,
    )
    resp = await client.post(
        "/admin/api-keys",
        json={"tenant_id": "rl-tenant", "label": "rl-key", "scopes": ["write:logs"]},
        headers=_ADMIN,
    )
    return resp.json()["key"]


async def test_rate_limit_blocks_after_threshold(async_client: AsyncClient):
    key = await _setup(async_client, limit=5)
    headers = {"Authorization": f"Bearer {key}"}

    for _ in range(5):
        resp = await async_client.post("/v1/logs", json=_SAMPLE, headers=headers)
        assert resp.status_code == 202

    resp = await async_client.post("/v1/logs", json=_SAMPLE, headers=headers)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"


async def test_rate_limit_status_endpoint(async_client: AsyncClient):
    key = await _setup(async_client, limit=10)
    headers = {"Authorization": f"Bearer {key}"}

    await async_client.post("/v1/logs", json=_SAMPLE, headers=headers)
    await async_client.post("/v1/logs", json=_SAMPLE, headers=headers)

    resp = await async_client.get(
        "/admin/tenants/rl-tenant/rate-limit-status", headers=_ADMIN
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit_per_min"] == 10
    assert data["current_count"] == 2


async def test_legacy_token_not_rate_limited(async_client: AsyncClient):
    await async_client.post(
        "/admin/tenants",
        json={"id": "rl-tenant", "name": "RL Tenant"},
        headers=_ADMIN,
    )
    await async_client.put(
        "/admin/tenants/rl-tenant/config",
        json={"config": {"rate_limit_per_min": 2}},
        headers=_ADMIN,
    )
    for _ in range(5):
        resp = await async_client.post("/v1/logs", json=_SAMPLE, headers=_ADMIN)
        assert resp.status_code == 202
