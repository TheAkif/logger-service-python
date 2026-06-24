import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .keys import ApiKeyRecord, lookup_key
from .settings import INGEST_TOKEN

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

ALL_SCOPES = ["write:logs", "read:logs", "admin"]


async def _resolve_key(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Optional[ApiKeyRecord]:
    if creds is None or creds.scheme.lower() != "bearer":
        return None

    raw = creds.credentials

    from . import db
    pool = db.get_pool()
    if pool is not None:
        record = await lookup_key(pool, raw)
        if record is not None:
            return record

    if INGEST_TOKEN and raw == INGEST_TOKEN:
        logger.warning("auth_legacy_token", extra={"reason": "INGEST_TOKEN fallback used"})
        return ApiKeyRecord(
            id=None,
            tenant_id="__legacy__",
            scopes=ALL_SCOPES,
            label="legacy-env-token",
            expires_at=None,
        )

    return None


def _require_scope(scope: str):
    async def _check(
        request: Request,
        creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    ) -> ApiKeyRecord:
        if not INGEST_TOKEN:
            return ApiKeyRecord(
                id=None,
                tenant_id="__dev__",
                scopes=ALL_SCOPES,
                label="dev-no-auth",
                expires_at=None,
            )

        record = await _resolve_key(request, creds)

        if record is None:
            if creds is None:
                raise HTTPException(status_code=403, detail="missing bearer token")
            logger.warning("auth_failed", extra={"reason": "invalid token"})
            raise HTTPException(status_code=401, detail="unauthorized")

        if scope not in record.scopes:
            raise HTTPException(status_code=403, detail=f"scope required: {scope}")

        return record

    return _check


require_token = _require_scope("write:logs")
require_read = _require_scope("read:logs")
require_admin = _require_scope("admin")
