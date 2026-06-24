import pytest
from httpx import AsyncClient

_ADMIN = {"Authorization": "Bearer test-token"}
_TENANT = {"id": "authtest", "name": "Auth Test Tenant"}

_SAMPLE = {
    "tenantId": "authtest",
    "source": "svc",
    "environment": "dev",
    "level": "info",
    "type": "app",
    "message": "auth test event",
}


async def _create_key(client: AsyncClient, scopes: list[str]) -> str:
    await client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    resp = await client.post(
        "/admin/api-keys",
        json={"tenant_id": "authtest", "label": "test", "scopes": scopes},
        headers=_ADMIN,
    )
    assert resp.status_code == 201
    return resp.json()["key"]


# ---- scope enforcement ------------------------------------------------------

async def test_write_key_can_ingest(async_client: AsyncClient):
    key = await _create_key(async_client, ["write:logs"])
    resp = await async_client.post(
        "/v1/logs", json=_SAMPLE, headers={"Authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 202


async def test_write_key_cannot_read(async_client: AsyncClient):
    key = await _create_key(async_client, ["write:logs"])
    resp = await async_client.get(
        "/v1/logs", headers={"Authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 403


async def test_read_key_can_query(async_client: AsyncClient):
    key = await _create_key(async_client, ["read:logs"])
    resp = await async_client.get(
        "/v1/logs", headers={"Authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 200


async def test_read_key_cannot_ingest(async_client: AsyncClient):
    key = await _create_key(async_client, ["read:logs"])
    resp = await async_client.post(
        "/v1/logs", json=_SAMPLE, headers={"Authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 403


async def test_invalid_key_returns_401(async_client: AsyncClient):
    resp = await async_client.post(
        "/v1/logs", json=_SAMPLE, headers={"Authorization": "Bearer lis_totallywrong"}
    )
    assert resp.status_code == 401


async def test_legacy_ingest_token_still_works(async_client: AsyncClient):
    resp = await async_client.post(
        "/v1/logs", json=_SAMPLE, headers={"Authorization": "Bearer test-token"}
    )
    assert resp.status_code == 202
