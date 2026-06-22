import pytest
from httpx import AsyncClient


# ── /health ──────────────────────────────────────────────────────────────────

async def test_health(async_client: AsyncClient):
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── /ready ───────────────────────────────────────────────────────────────────

async def test_ready(async_client: AsyncClient):
    resp = await async_client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


# ── POST /v1/logs - auth ─────────────────────────────────────────────────────

async def test_post_log_no_token(async_client: AsyncClient, sample_log: dict):
    resp = await async_client.post("/v1/logs", json=sample_log)
    assert resp.status_code == 403


async def test_post_log_wrong_token(async_client: AsyncClient, sample_log: dict):
    resp = await async_client.post(
        "/v1/logs", json=sample_log,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


# ── POST /v1/logs - happy path ────────────────────────────────────────────────

async def test_post_log_returns_202(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["accepted"] is True


# ── POST /v1/logs - validation ───────────────────────────────────────────────

async def test_post_log_missing_required_field(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    del sample_log["message"]
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 422


async def test_post_log_placeholder_string_rejected(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    sample_log["tenantId"] = "string"
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 422


async def test_post_log_empty_message_rejected(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    sample_log["message"] = ""
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 422


async def test_post_log_unknown_field_rejected(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    sample_log["unknownField"] = "oops"
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 422


async def test_post_log_invalid_level(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    sample_log["level"] = "verbose"
    resp = await async_client.post("/v1/logs", json=sample_log, headers=auth_headers)
    assert resp.status_code == 422


# ── POST /v1/logs/batch ───────────────────────────────────────────────────────

async def test_post_batch_happy_path(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    events = [sample_log] * 5
    resp = await async_client.post("/v1/logs/batch", json=events, headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["count"] == 5
    assert resp.json()["accepted"] is True


async def test_post_batch_too_large(
    async_client: AsyncClient, auth_headers: dict, sample_log: dict
):
    events = [sample_log] * 501
    resp = await async_client.post("/v1/logs/batch", json=events, headers=auth_headers)
    assert resp.status_code == 413


async def test_post_batch_no_token(async_client: AsyncClient, sample_log: dict):
    resp = await async_client.post("/v1/logs/batch", json=[sample_log])
    assert resp.status_code == 403
