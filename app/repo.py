import json
from datetime import datetime, timezone
from typing import List

import app.db as db
from .models import LogEvent


_INSERT_SQL = """
INSERT INTO log_events (
  occurred_at, tenant_id, source, environment, level, type, message,
  trace_id, span_id, correlation_id, request_id,
  user_id, path, method, status_code, duration_ms,
  exception, properties
)
VALUES (
  $1,$2,$3,$4,$5,$6,$7,
  $8,$9,$10,$11,
  $12,$13,$14,$15,$16,
  $17::jsonb,$18::jsonb
)
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_jsonb(value):
    if value is None:
        return None
    # asyncpg accepts JSONB as a string
    return json.dumps(value, ensure_ascii=False)


async def insert_one(e: LogEvent) -> None:
    pool = db.get_pool()

    occurred_at = e.occurredAt or _utc_now()

    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_SQL,
            occurred_at,
            e.tenantId, e.source, e.environment, e.level, e.type, e.message,
            e.traceId, e.spanId, e.correlationId, e.requestId,
            e.userId, e.path, e.method, e.statusCode, e.durationMs,
            _to_jsonb(e.exception),
            _to_jsonb(e.properties),
        )


async def insert_batch(events: List[LogEvent]) -> None:
    if not events:
        return

    pool = db.get_pool()
    now = _utc_now()

    rows = []
    for e in events:
        occurred_at = e.occurredAt or now
        rows.append((
            occurred_at,
            e.tenantId, e.source, e.environment, e.level, e.type, e.message,
            e.traceId, e.spanId, e.correlationId, e.requestId,
            e.userId, e.path, e.method, e.statusCode, e.durationMs,
            _to_jsonb(e.exception),
            _to_jsonb(e.properties),
        ))

    async with pool.acquire() as conn:
        # MVP bulk insert (fast enough for now). We can switch to COPY later.
        await conn.executemany(_INSERT_SQL, rows)
