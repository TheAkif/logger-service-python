from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg


async def search_logs(
    pool: asyncpg.Pool,
    tenant_id: Optional[str] = None,
    source: Optional[str] = None,
    level: Optional[str] = None,
    log_type: Optional[str] = None,
    environment: Optional[str] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[dict], int]:
    conditions: list[str] = []
    params: list = []

    def add(condition: str, value) -> None:
        params.append(value)
        conditions.append(condition.replace("?", f"${len(params)}"))

    if tenant_id is not None:
        add("tenant_id = ?", tenant_id)
    if source is not None:
        add("source = ?", source)
    if level is not None:
        add("level = ?", level)
    if log_type is not None:
        add("type = ?", log_type)
    if environment is not None:
        add("environment = ?", environment)
    if from_dt is not None:
        add("occurred_at >= ?", from_dt)
    if to_dt is not None:
        add("occurred_at <= ?", to_dt)
    if trace_id is not None:
        add("trace_id = ?", trace_id)
    if user_id is not None:
        add("user_id = ?", user_id)
    if q is not None:
        add("message_tsv @@ plainto_tsquery('english', ?)", q)

    where = " AND ".join(conditions) if conditions else "TRUE"

    paginated = params + [limit, (page - 1) * limit]
    limit_ph = f"${len(paginated) - 1}"
    offset_ph = f"${len(paginated)}"

    select = """
        SELECT id, occurred_at, received_at,
               tenant_id, source, environment, level, type, message,
               trace_id, span_id, correlation_id, request_id,
               user_id, path, method, status_code, duration_ms,
               exception, properties
        FROM log_events
    """

    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            f"SELECT COUNT(*) FROM log_events WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"{select} WHERE {where} ORDER BY occurred_at DESC"
            f" LIMIT {limit_ph} OFFSET {offset_ph}",
            *paginated,
        )

    return [dict(r) for r in rows], total


async def get_log_by_id(pool: asyncpg.Pool, log_id: UUID) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, occurred_at, received_at,
                   tenant_id, source, environment, level, type, message,
                   trace_id, span_id, correlation_id, request_id,
                   user_id, path, method, status_code, duration_ms,
                   exception, properties
            FROM log_events WHERE id = $1
            """,
            log_id,
        )
    return dict(row) if row else None
