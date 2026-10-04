# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Redis Streams event bus: one global stream + one stream per task for replay."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from uuid import UUID

from hydra.bus.base import EventBus, EventHandler
from hydra.core.events import EventType, HydraEvent

log = logging.getLogger("hydra.bus.redis")

GLOBAL_STREAM = "hydra:events"


class RedisStreamsEventBus(EventBus):
    def __init__(self, url: str, task_ttl_s: int = 7 * 24 * 3600, maxlen: int = 100_000) -> None:
        import redis.asyncio as redis  # optional dependency

        self._redis = redis.from_url(url, decode_responses=True)
        self._handlers: dict[EventType | None, list[EventHandler]] = defaultdict(list)
        self._task_ttl_s = task_ttl_s
        self._maxlen = maxlen
        self._reader: asyncio.Task | None = None

    @staticmethod
    def _task_stream(task_id: UUID) -> str:
        return f"hydra:task:{task_id}"

    async def publish(self, event: HydraEvent) -> None:
        data = {"event": event.model_dump_json()}
        pipe = self._redis.pipeline()
        pipe.xadd(GLOBAL_STREAM, data, maxlen=self._maxlen, approximate=True)
        pipe.xadd(self._task_stream(event.task_id), data)
        pipe.expire(self._task_stream(event.task_id), self._task_ttl_s)
        await pipe.execute()

    async def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)
        if self._reader is None:
            self._reader = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        last_id = "$"
        while True:
            try:
                batches = await self._redis.xread({GLOBAL_STREAM: last_id}, block=5000, count=100)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("redis xread failed")
                await asyncio.sleep(1)
                continue
            for _stream, entries in batches or []:
                for entry_id, fields in entries:
                    last_id = entry_id
                    event = HydraEvent.model_validate_json(fields["event"])
                    for handler in (*self._handlers[event.type], *self._handlers[None]):
                        try:
                            await handler(event)
                        except Exception:
                            log.exception("event handler failed")

    async def history(self, task_id: UUID) -> list[HydraEvent]:
        entries = await self._redis.xrange(self._task_stream(task_id))
        return [HydraEvent.model_validate_json(f["event"]) for _, f in entries]

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        await self._redis.aclose()
