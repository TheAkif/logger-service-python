import asyncio
import json
import logging
import time
from typing import List, Optional

from .models import LogEvent
from .settings import BATCH_MAX, BATCH_FLUSH_SEC, QUEUE_MAX
from . import repo

logger = logging.getLogger(__name__)


class Batcher:
    def __init__(self):
        self._q: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: Optional[asyncio.Task] = None
        self._flush_lock = asyncio.Lock()

        self.enqueued = 0
        self.dropped = 0
        self.flushed = 0
        self.flush_errors = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="log-batcher")
        logger.info("batcher_started", extra={"queue_max": QUEUE_MAX, "batch_max": BATCH_MAX})

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.flush_now()
        logger.info("batcher_stopped", extra={"flushed": self.flushed, "dropped": self.dropped})

    def enqueue_nowait(self, e: LogEvent) -> bool:
        try:
            self._q.put_nowait(e)
            self.enqueued += 1
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("batcher_queue_full", extra={"dropped_total": self.dropped})
            return False

    async def enqueue(self, e: LogEvent) -> None:
        await self._q.put(e)
        self.enqueued += 1

    async def flush_now(self) -> None:
        async with self._flush_lock:
            batch = self._drain_up_to(BATCH_MAX)
            if batch:
                await self._write_batch(batch)

    def _drain_up_to(self, n: int) -> List[LogEvent]:
        items: List[LogEvent] = []
        while len(items) < n:
            try:
                items.append(self._q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    async def _write_batch(self, batch: List[LogEvent]) -> None:
        t0 = time.monotonic()
        try:
            await repo.insert_batch(batch)
            self.flushed += len(batch)
            logger.info(
                "batch_flushed",
                extra={"count": len(batch), "duration_ms": round((time.monotonic() - t0) * 1000)},
            )
        except Exception as exc:
            self.flush_errors += 1
            logger.error("batch_flush_error", extra={"count": len(batch), "error": str(exc)})
            await self._write_dead_letter(batch, exc)

    async def _write_dead_letter(self, batch: List[LogEvent], exc: Exception) -> None:
        from . import db

        payload = json.dumps([e.model_dump(mode="json") for e in batch], default=str)
        try:
            async with db.get_pool().acquire() as conn:
                await conn.execute(
                    "INSERT INTO failed_batches (payload, error) VALUES ($1::jsonb, $2)",
                    payload,
                    str(exc),
                )
            logger.warning("dead_letter_written", extra={"count": len(batch)})
        except Exception as dl_exc:
            logger.error(
                "dead_letter_failed",
                extra={"count": len(batch), "error": str(dl_exc)},
            )

    async def _run(self) -> None:
        while True:
            try:
                try:
                    first = await asyncio.wait_for(self._q.get(), timeout=BATCH_FLUSH_SEC)
                    batch = [first]
                except asyncio.TimeoutError:
                    batch = []

                if batch:
                    batch.extend(self._drain_up_to(BATCH_MAX - len(batch)))
                else:
                    continue

                await self._write_batch(batch)

                # drain aggressively if queue is still backed up, but yield between passes
                while self._q.qsize() >= BATCH_MAX:
                    await asyncio.sleep(0)
                    await self.flush_now()

            except asyncio.CancelledError:
                break
