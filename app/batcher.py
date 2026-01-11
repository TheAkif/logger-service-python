import asyncio
from typing import List, Optional

from .models import LogEvent
from .settings import BATCH_MAX, BATCH_FLUSH_SEC, QUEUE_MAX
from . import repo


class Batcher:
    def __init__(self):
        self._q: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self._flush_lock = asyncio.Lock()

        # simple counters (optional but useful)
        self.enqueued = 0
        self.dropped = 0
        self.flushed = 0
        self.flush_errors = 0

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="log-batcher")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # final flush on shutdown
        await self.flush_now()

    def enqueue_nowait(self, e: LogEvent) -> bool:
        """
        Fast path for HTTP handlers.
        Returns True if queued, False if dropped (queue full).
        """
        try:
            self._q.put_nowait(e)
            self.enqueued += 1
            return True
        except asyncio.QueueFull:
            self.dropped += 1
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
        try:
            await repo.insert_batch(batch)  # one transaction inside repo (we’ll ensure that)
            self.flushed += len(batch)
        except Exception:
            self.flush_errors += 1
            # Minimal behavior: drop on error (MVP).
            # Later we can add retry/spool file, etc.
            # We do NOT requeue to avoid infinite loops.

    async def _run(self) -> None:
        """
        Flush policy:
          - flush if we have >= BATCH_MAX quickly
          - otherwise flush every BATCH_FLUSH_SEC
        """
        while not self._stopping.is_set():
            try:
                # wait for at least one item or timeout
                try:
                    first = await asyncio.wait_for(self._q.get(), timeout=BATCH_FLUSH_SEC)
                    batch = [first]
                except asyncio.TimeoutError:
                    batch = []

                # drain remaining up to BATCH_MAX
                if batch:
                    batch.extend(self._drain_up_to(BATCH_MAX - len(batch)))
                else:
                    # timeout with empty queue
                    continue

                # if we got any, write them
                await self._write_batch(batch)

                # if queue is still huge, keep flushing without sleeping
                while self._q.qsize() >= BATCH_MAX:
                    await self.flush_now()

            except asyncio.CancelledError:
                break
