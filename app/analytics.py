from datetime import datetime
from typing import Optional

import asyncpg


async def get_summary(
    pool: asyncpg.Pool,
    tenant_id: str,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> dict:
    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]

    if from_dt is not None:
        params.append(from_dt)
        conditions.append(f"occurred_at >= ${len(params)}")
    if to_dt is not None:
        params.append(to_dt)
        conditions.append(f"occurred_at <= ${len(params)}")

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        by_level = await conn.fetch(
            f"SELECT level, COUNT(*) AS count FROM log_events WHERE {where} GROUP BY level",
            *params,
        )
        by_type = await conn.fetch(
            f"SELECT type, COUNT(*) AS count FROM log_events WHERE {where} GROUP BY type",
            *params,
        )
        by_source = await conn.fetch(
            f"""SELECT source, COUNT(*) AS count FROM log_events WHERE {where}
                GROUP BY source ORDER BY count DESC LIMIT 10""",
            *params,
        )

    return {
        "by_level": {r["level"]: r["count"] for r in by_level},
        "by_type": {r["type"]: r["count"] for r in by_type},
        "by_source": {r["source"]: r["count"] for r in by_source},
    }


async def get_timeline(
    pool: asyncpg.Pool,
    tenant_id: str,
    interval: str = "hour",
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list[dict]:
    trunc = "hour" if interval == "hour" else "day"

    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]

    if from_dt is not None:
        params.append(from_dt)
        conditions.append(f"occurred_at >= ${len(params)}")
    if to_dt is not None:
        params.append(to_dt)
        conditions.append(f"occurred_at <= ${len(params)}")

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT date_trunc('{trunc}', occurred_at) AS bucket, COUNT(*) AS count
            FROM log_events WHERE {where}
            GROUP BY bucket ORDER BY bucket
            """,
            *params,
        )

    return [{"bucket": r["bucket"].isoformat(), "count": r["count"]} for r in rows]


async def get_top_sources(
    pool: asyncpg.Pool,
    tenant_id: str,
    n: int = 10,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list[dict]:
    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]

    if from_dt is not None:
        params.append(from_dt)
        conditions.append(f"occurred_at >= ${len(params)}")
    if to_dt is not None:
        params.append(to_dt)
        conditions.append(f"occurred_at <= ${len(params)}")

    params.append(n)
    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT source, COUNT(*) AS count
            FROM log_events WHERE {where}
            GROUP BY source ORDER BY count DESC LIMIT ${len(params)}
            """,
            *params,
        )

    return [{"source": r["source"], "count": r["count"]} for r in rows]


async def get_error_rate(
    pool: asyncpg.Pool,
    tenant_id: str,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                date_trunc('hour', occurred_at) AS bucket,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE level IN ('error', 'fatal')) AS errors
            FROM log_events
            WHERE tenant_id = $1
              AND occurred_at >= now() - INTERVAL '24 hours'
            GROUP BY bucket ORDER BY bucket
            """,
            tenant_id,
        )

    return [
        {
            "bucket": r["bucket"].isoformat(),
            "total": r["total"],
            "errors": r["errors"],
            "error_rate_pct": round(r["errors"] / r["total"] * 100, 2) if r["total"] else 0.0,
        }
        for r in rows
    ]
