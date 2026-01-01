from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi import Depends, HTTPException
from typing import List

from .models import LogEvent, BatchIngestResponse
from .security import require_token
from . import repo


from . import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    try:
        yield
    finally:
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
    except Exception as e:
        raise HTTPException(status_code=503, detail="db not ready")

@app.post(
    "/v1/logs",
    status_code=202,
    dependencies=[Depends(require_token)],
    summary="Ingest a single log event",
    description="Accepts one log event and stores it in Postgres."
)
async def post_log(e: LogEvent):
    await repo.insert_one(e)
    return {"accepted": True}



@app.post(
    "/v1/logs/batch",
    status_code=202,
    response_model=BatchIngestResponse,
    dependencies=[Depends(require_token)],
    summary="Ingest multiple log events",
    description="Accepts an array of log events and stores them in Postgres (bulk insert)."
)
async def post_logs_batch(events: List[LogEvent]):
    if len(events) > 500:
        raise HTTPException(status_code=413, detail="batch too large (max 500)")
    await repo.insert_batch(events)
    return BatchIngestResponse(count=len(events))
