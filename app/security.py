from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .settings import INGEST_TOKEN

bearer = HTTPBearer(auto_error=False)

def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    if not INGEST_TOKEN:
        return

    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
