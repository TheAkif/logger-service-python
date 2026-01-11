from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from typing import List

from .models import LogEvent, BatchIngestResponse
from .security import require_token
from . import db
from .batcher import Batcher

# single in-process batcher instance
batcher = Batcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await batcher.start()
    try:
        yield
    finally:
        await batcher.stop()
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
    description="Accepts one log event and enqueues it for batched insert into Postgres."
)
async def post_log(e: LogEvent):
    ok = batcher.enqueue_nowait(e)
    if not ok:
        # backpressure when queue is full
        raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")
    return {"accepted": True}


@app.post(
    "/v1/logs/batch",
    status_code=202,
    response_model=BatchIngestResponse,
    dependencies=[Depends(require_token)],
    summary="Ingest multiple log events",
    description="Accepts an array of log events and enqueues them for batched insert into Postgres."
)
async def post_logs_batch(events: List[LogEvent]):
    if len(events) > 500:
        raise HTTPException(status_code=413, detail="batch too large (max 500)")

    for e in events:
        if not batcher.enqueue_nowait(e):
            raise HTTPException(status_code=503, detail="ingestor overloaded (queue full)")

    return BatchIngestResponse(count=len(events))

import os
# Optional: quick visibility during load testing (remove later if you want)
@app.get("/internal/batcher")
async def batcher_stats():
    return {
        "pid": os.getpid(),
        "queued": batcher._q.qsize(),  # ok for internal endpoint; keep private
        "enqueued": batcher.enqueued,
        "flushed": batcher.flushed,
        "dropped": batcher.dropped,
        "flush_errors": batcher.flush_errors,
    }
