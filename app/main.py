import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .logging_config import setup_logging
from .models import BatchIngestResponse, LogEvent, LogQueryResponse, LogRecord
from .security import ApiKeyRecord, require_token, require_read
from .settings import ENV, INGEST_TOKEN
from . import admin as admin_module
from . import analytics, db, query as query_module
from . import ratelimit
from .batcher import Batcher

setup_logging()
logger = logging.getLogger(__name__)

batcher = Batcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not INGEST_TOKEN and ENV != "dev":
        raise RuntimeError(
            "INGEST_TOKEN must be set in non-dev environments. "
            "Set the INGEST_TOKEN environment variable."
        )
    if not INGEST_TOKEN:
        logger.warning("auth_disabled", extra={"reason": "INGEST_TOKEN not set, ENV=dev"})
    else:
        logger.info("auth_enabled")

    await db.connect()
    await batcher.start()
    try:
        yield
    finally:
        try:
            await asyncio.wait_for(batcher.stop(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("batcher_stop_timeout", extra={"timeout_sec": 30})
        await db.disconnect()


app = FastAPI(title="LIS Log Ingestor", lifespan=lifespan)
app.include_router(admin_module.router)


# ---- Liveness / readiness ---------------------------------------------------

@app.get("/health", tags=["internal"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["internal"])
async def ready():
    try:
        await db.ping()
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="db not ready")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    html = (Path(__file__).parent / "static" / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# ---- Ingest -----------------------------------------------------------------

def _check_rate_limit(key: ApiKeyRecord, pool):
    async def _inner():
        tenant_id = key.tenant_id
        if tenant_id in ("__legacy__", "__dev__"):
            return
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config FROM tenants WHERE id = $1 AND deleted_at IS NULL", tenant_id
            )
        if row is None:
            return
        limit = row["config"].get("rate_limit_per_min")
        if not ratelimit.check_rate_limit(tenant_id, limit):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "60"},
            )
    return _inner


@app.post(
    "/v1/logs",
    status_code=202,
    tags=["ingest"],
    summary="Ingest a single log event",
)
async def post_log(
    e: LogEvent,
    key: ApiKeyRecord = Depends(require_token),
):
    pool = db.get_pool()
    await _check_rate_limit(key, pool)()
    ok = batcher.enqueue_nowait(e)
    if not ok:
        logger.warning("ingest_rejected", extra={"reason": "queue_full"})
        raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")
    return {"accepted": True}


@app.post(
    "/v1/logs/batch",
    status_code=202,
    response_model=BatchIngestResponse,
    tags=["ingest"],
    summary="Ingest multiple log events",
)
async def post_logs_batch(
    events: List[LogEvent],
    key: ApiKeyRecord = Depends(require_token),
):
    if len(events) > 500:
        raise HTTPException(status_code=413, detail="batch too large (max 500)")

    pool = db.get_pool()
    await _check_rate_limit(key, pool)()

    for e in events:
        if not batcher.enqueue_nowait(e):
            logger.warning("ingest_rejected", extra={"reason": "queue_full"})
            raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")

    return BatchIngestResponse(count=len(events))


# ---- Query ------------------------------------------------------------------

@app.get(
    "/v1/logs",
    response_model=LogQueryResponse,
    tags=["query"],
    summary="Query log events with optional filters",
)
async def get_logs(
    key: ApiKeyRecord = Depends(require_read),
    tenant_id: Optional[str] = None,
    source: Optional[str] = None,
    level: Optional[str] = None,
    log_type: Optional[str] = Query(None, alias="type"),
    environment: Optional[str] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    pool = db.get_pool()
    rows, total = await query_module.search_logs(
        pool,
        tenant_id=tenant_id,
        source=source,
        level=level,
        log_type=log_type,
        environment=environment,
        from_dt=from_dt,
        to_dt=to_dt,
        trace_id=trace_id,
        user_id=user_id,
        q=q,
        page=page,
        limit=limit,
    )
    return LogQueryResponse(
        total=total,
        page=page,
        limit=limit,
        items=[LogRecord.model_validate(row) for row in rows],
    )


@app.get(
    "/v1/logs/{log_id}",
    response_model=LogRecord,
    tags=["query"],
    summary="Get a single log event by ID",
)
async def get_log(
    log_id: UUID,
    key: ApiKeyRecord = Depends(require_read),
):
    pool = db.get_pool()
    row = await query_module.get_log_by_id(pool, log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="log event not found")
    return LogRecord.model_validate(row)


# ---- Analytics --------------------------------------------------------------

@app.get(
    "/v1/analytics/summary",
    tags=["analytics"],
    summary="Event counts grouped by level, type, and source",
)
async def analytics_summary(
    tenant_id: str,
    key: ApiKeyRecord = Depends(require_read),
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
):
    pool = db.get_pool()
    return await analytics.get_summary(pool, tenant_id, from_dt, to_dt)


@app.get(
    "/v1/analytics/timeline",
    tags=["analytics"],
    summary="Event count per hour or day for a time window",
)
async def analytics_timeline(
    tenant_id: str,
    key: ApiKeyRecord = Depends(require_read),
    interval: str = Query("hour", pattern="^(hour|day)$"),
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
):
    pool = db.get_pool()
    return await analytics.get_timeline(pool, tenant_id, interval, from_dt, to_dt)


@app.get(
    "/v1/analytics/top-sources",
    tags=["analytics"],
    summary="Top N sources by event count",
)
async def analytics_top_sources(
    tenant_id: str,
    key: ApiKeyRecord = Depends(require_read),
    n: int = Query(10, ge=1, le=50),
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
):
    pool = db.get_pool()
    return await analytics.get_top_sources(pool, tenant_id, n, from_dt, to_dt)


@app.get(
    "/v1/analytics/error-rate",
    tags=["analytics"],
    summary="Error and fatal rate per hour over the last 24 hours",
)
async def analytics_error_rate(
    tenant_id: str,
    key: ApiKeyRecord = Depends(require_read),
):
    pool = db.get_pool()
    return await analytics.get_error_rate(pool, tenant_id)


# ---- Internal ---------------------------------------------------------------

@app.get("/internal/health", tags=["internal"])
async def internal_health():
    return {
        "pid": os.getpid(),
        "queued": batcher._q.qsize(),
        "enqueued": batcher.enqueued,
        "flushed": batcher.flushed,
        "dropped": batcher.dropped,
        "flush_errors": batcher.flush_errors,
        "uptime_sec": round(time.monotonic() - batcher._started_at),
        "last_flush_at": batcher._last_flush_at,
    }


@app.get("/metrics", tags=["internal"], include_in_schema=False)
async def metrics_endpoint():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
