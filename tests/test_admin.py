import pytest
from httpx import AsyncClient


_ADMIN = {"Authorization": "Bearer test-token"}

_TENANT = {"id": "acme", "name": "Acme Corp"}


# ---- tenants ----------------------------------------------------------------

async def test_create_tenant(async_client: AsyncClient):
    resp = await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "acme"
    assert data["name"] == "Acme Corp"


async def test_create_tenant_duplicate(async_client: AsyncClient):
    await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    resp = await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    assert resp.status_code == 409


async def test_list_tenants(async_client: AsyncClient):
    await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    await async_client.post("/admin/tenants", json={"id": "beta", "name": "Beta"}, headers=_ADMIN)

    resp = await async_client.get("/admin/tenants", headers=_ADMIN)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert "acme" in ids
    assert "beta" in ids


async def test_get_tenant(async_client: AsyncClient):
    await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    resp = await async_client.get("/admin/tenants/acme", headers=_ADMIN)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme Corp"


async def test_get_tenant_not_found(async_client: AsyncClient):
    resp = await async_client.get("/admin/tenants/nonexistent", headers=_ADMIN)
    assert resp.status_code == 404


async def test_update_tenant_config(async_client: AsyncClient):
    await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    resp = await async_client.put(
        "/admin/tenants/acme/config",
        json={"config": {"rate_limit_per_min": 100, "retention_days": 30}},
        headers=_ADMIN,
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["rate_limit_per_min"] == 100


async def test_delete_tenant(async_client: AsyncClient):
    await async_client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)
    resp = await async_client.delete("/admin/tenants/acme", headers=_ADMIN)
    assert resp.status_code == 204

    resp = await async_client.get("/admin/tenants/acme", headers=_ADMIN)
    assert resp.status_code == 404


async def test_admin_requires_auth(async_client: AsyncClient):
    resp = await async_client.get("/admin/tenants")
    assert resp.status_code == 403


# ---- api keys ---------------------------------------------------------------

async def _make_tenant(client: AsyncClient):
    await client.post("/admin/tenants", json=_TENANT, headers=_ADMIN)


async def test_create_api_key_returns_raw_key(async_client: AsyncClient):
    await _make_tenant(async_client)
    resp = await async_client.post(
        "/admin/api-keys",
        json={"tenant_id": "acme", "label": "ci-key", "scopes": ["write:logs"]},
        headers=_ADMIN,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"].startswith("lis_")
    assert "key_hash" not in data


async def test_raw_key_not_in_list(async_client: AsyncClient):
    await _make_tenant(async_client)
    create = await async_client.post(
        "/admin/api-keys",
        json={"tenant_id": "acme", "label": "ci-key", "scopes": ["write:logs"]},
        headers=_ADMIN,
    )
    assert create.status_code == 201

    list_resp = await async_client.get("/admin/api-keys?tenant_id=acme", headers=_ADMIN)
    assert list_resp.status_code == 200
    for key in list_resp.json():
        assert "key" not in key


async def test_revoke_key_blocks_auth(async_client: AsyncClient):
    await _make_tenant(async_client)
    create = await async_client.post(
        "/admin/api-keys",
        json={"tenant_id": "acme", "label": "temp", "scopes": ["write:logs", "read:logs"]},
        headers=_ADMIN,
    )
    raw_key = create.json()["key"]
    key_id = create.json()["id"]

    resp = await async_client.get(
        "/v1/logs", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert resp.status_code == 200

    await async_client.delete(f"/admin/api-keys/{key_id}", headers=_ADMIN)

    resp = await async_client.get(
        "/v1/logs", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert resp.status_code == 401
