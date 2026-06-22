import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, HTTPException

from .logging_config import setup_logging
from .models import BatchIngestResponse, LogEvent
from .security import require_token
from .settings import ENV, INGEST_TOKEN
from . import db
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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    try:
        await db.ping()
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="db not ready")


@app.post(
    "/v1/logs",
    status_code=202,
    dependencies=[Depends(require_token)],
    summary="Ingest a single log event",
    description="Accepts one log event and enqueues it for batched insert into Postgres.",
)
async def post_log(e: LogEvent):
    ok = batcher.enqueue_nowait(e)
    if not ok:
        logger.warning("ingest_rejected", extra={"reason": "queue_full"})
        raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")
    return {"accepted": True}


@app.post(
    "/v1/logs/batch",
    status_code=202,
    response_model=BatchIngestResponse,
    dependencies=[Depends(require_token)],
    summary="Ingest multiple log events",
    description="Accepts an array of log events and enqueues them for batched insert into Postgres.",
)
async def post_logs_batch(events: List[LogEvent]):
    if len(events) > 500:
        raise HTTPException(status_code=413, detail="batch too large (max 500)")

    for e in events:
        if not batcher.enqueue_nowait(e):
            logger.warning("ingest_rejected", extra={"reason": "queue_full"})
            raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")

    return BatchIngestResponse(count=len(events))


@app.get("/internal/batcher")
async def batcher_stats():
    return {
        "pid": os.getpid(),
        "queued": batcher._q.qsize(),
        "enqueued": batcher.enqueued,
        "flushed": batcher.flushed,
        "dropped": batcher.dropped,
        "flush_errors": batcher.flush_errors,
    }
