from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from . import db
from .keys import ApiKeyRecord, generate_key, hash_key
from .security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- models ----------------------------------------------------------------

class TenantCreate(BaseModel):
    id: str
    name: str
    config: dict = {}


class TenantConfig(BaseModel):
    config: dict


class ApiKeyCreate(BaseModel):
    tenant_id: str
    label: str
    scopes: List[str]
    expires_at: Optional[datetime] = None


# ---- tenants ----------------------------------------------------------------

@router.post("/tenants", status_code=201, dependencies=[Depends(require_admin)])
async def create_tenant(body: TenantCreate):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM tenants WHERE id = $1", body.id
        )
        if existing:
            raise HTTPException(status_code=409, detail="tenant already exists")
        row = await conn.fetchrow(
            """
            INSERT INTO tenants (id, name, config)
            VALUES ($1, $2, $3)
            RETURNING id, name, created_at, config
            """,
            body.id, body.name, body.config,
        )
    return dict(row)


@router.get("/tenants", dependencies=[Depends(require_admin)])
async def list_tenants():
    pool = db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                t.id,
                t.name,
                t.created_at,
                t.config,
                COUNT(DISTINCT k.id) FILTER (WHERE k.revoked = false) AS active_keys,
                COUNT(e.id) FILTER (
                    WHERE e.received_at > now() - INTERVAL '24 hours'
                ) AS events_24h
            FROM tenants t
            LEFT JOIN api_keys k ON k.tenant_id = t.id
            LEFT JOIN log_events e ON e.tenant_id = t.id
            WHERE t.deleted_at IS NULL
            GROUP BY t.id, t.name, t.created_at, t.config
            ORDER BY t.created_at DESC
            """
        )
    return [dict(r) for r in rows]


@router.get("/tenants/{tenant_id}", dependencies=[Depends(require_admin)])
async def get_tenant(tenant_id: str):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, created_at, config FROM tenants WHERE id = $1 AND deleted_at IS NULL",
            tenant_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return dict(row)


@router.put("/tenants/{tenant_id}/config", dependencies=[Depends(require_admin)])
async def update_tenant_config(tenant_id: str, body: TenantConfig):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE tenants SET config = $2
            WHERE id = $1 AND deleted_at IS NULL
            RETURNING id, name, created_at, config
            """,
            tenant_id, body.config,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return dict(row)


@router.delete("/tenants/{tenant_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_tenant(tenant_id: str):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tenants SET deleted_at = now() WHERE id = $1 AND deleted_at IS NULL",
            tenant_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="tenant not found")


# ---- api keys ---------------------------------------------------------------

@router.post("/api-keys", status_code=201, dependencies=[Depends(require_admin)])
async def create_api_key(body: ApiKeyCreate):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        tenant = await conn.fetchval(
            "SELECT id FROM tenants WHERE id = $1 AND deleted_at IS NULL", body.tenant_id
        )
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")

        raw = generate_key()
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (tenant_id, key_hash, label, scopes, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, tenant_id, label, scopes, created_at, expires_at
            """,
            body.tenant_id, hash_key(raw), body.label, body.scopes, body.expires_at,
        )
    return {**dict(row), "key": raw}


@router.get("/api-keys", dependencies=[Depends(require_admin)])
async def list_api_keys(tenant_id: Optional[str] = Query(None)):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        if tenant_id:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, label, scopes, created_at, last_used_at,
                       expires_at, revoked
                FROM api_keys WHERE tenant_id = $1 ORDER BY created_at DESC
                """,
                tenant_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, label, scopes, created_at, last_used_at,
                       expires_at, revoked
                FROM api_keys ORDER BY created_at DESC
                """
            )
    return [dict(r) for r in rows]


@router.delete("/api-keys/{key_id}", status_code=204, dependencies=[Depends(require_admin)])
async def revoke_api_key(key_id: UUID):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET revoked = true WHERE id = $1 AND revoked = false",
            key_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="key not found or already revoked")


# ---- rate limit status ------------------------------------------------------

@router.get("/tenants/{tenant_id}/rate-limit-status", dependencies=[Depends(require_admin)])
async def rate_limit_status(tenant_id: str):
    from . import ratelimit
    pool = db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM tenants WHERE id = $1 AND deleted_at IS NULL", tenant_id
        )
    if row is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    limit = row["config"].get("rate_limit_per_min")
    count = ratelimit.current_count(tenant_id)
    return {"tenant_id": tenant_id, "current_count": count, "limit_per_min": limit}
