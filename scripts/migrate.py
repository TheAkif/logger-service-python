"""Run all SQL migration files in order against DATABASE_URL."""
import asyncio
import os
from pathlib import Path

import asyncpg


async def run() -> None:
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        migrations = sorted(Path(__file__).parent.parent.glob("migrations/*.sql"))
        for path in migrations:
            print(f"  applying {path.name}...", flush=True)
            await conn.execute(path.read_text())
        print(f"migrations complete ({len(migrations)} files)", flush=True)
    finally:
        await conn.close()


asyncio.run(run())
