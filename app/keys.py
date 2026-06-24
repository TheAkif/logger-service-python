import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg


@dataclass
class ApiKeyRecord:
    id: UUID
    tenant_id: str
    scopes: list[str]
    label: str
    expires_at: Optional[datetime]


def generate_key() -> str:
    return "lis_" + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def lookup_key(pool: asyncpg.Pool, raw: str) -> Optional[ApiKeyRecord]:
    h = hash_key(raw)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE api_keys
               SET last_used_at = now()
             WHERE key_hash = $1
               AND revoked = false
               AND (expires_at IS NULL OR expires_at > now())
         RETURNING id, tenant_id, scopes, label, expires_at
            """,
            h,
        )
    if row is None:
        return None
    return ApiKeyRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scopes=list(row["scopes"]),
        label=row["label"],
        expires_at=row["expires_at"],
    )
