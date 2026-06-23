import logging

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import INGEST_TOKEN

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    if not INGEST_TOKEN:
        return
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=403, detail="missing bearer token")
    if creds.credentials != INGEST_TOKEN:
        logger.warning("auth_failed", extra={"reason": "invalid token"})
        raise HTTPException(status_code=401, detail="unauthorized")
