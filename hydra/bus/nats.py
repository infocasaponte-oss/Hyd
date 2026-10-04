# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""NATS JetStream event bus: the evolution of Redis Streams for fan-out, distributed
workers and throughput. Subjects: ``hydra.events.<task_id>.<event_type>``."""

from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from hydra.bus.base import EventBus, EventHandler
from hydra.core.events import EventType, HydraEvent

log = logging.getLogger("hydra.bus.nats")

STREAM = "HYDRA"
SUBJECTS = "hydra.events.>"


class NatsEventBus(EventBus):
    def __init__(self, url: str, max_age_s: int = 7 * 24 * 3600) -> None:
        self.url = url
        self.max_age_s = max_age_s
        self._nc = None
        self._js = None
        self._handlers: dict[EventType | None, list[EventHandler]] = defaultdict(list)
        self._sub = None

    async def connect(self) -> None:
        if self._nc is not None:
            return
        import nats  # optional dependency: pip install nats-py
        from nats.js.api import StreamConfig

        self._nc = await nats.connect(self.url)
        self._js = self._nc.jetstream()
        try:
            await self._js.add_stream(StreamConfig(name=STREAM, subjects=[SUBJECTS], max_age=self.max_age_s))
        except Exception:
            await self._js.update_stream(StreamConfig(name=STREAM, subjects=[SUBJECTS], max_age=self.max_age_s))

    async def publish(self, event: HydraEvent) -> None:
        await self.connect()
        await self._js.publish(f"hydra.events.{event.task_id}.{event.type.value}",
                               event.model_dump_json().encode())

    async def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None:
        await self.connect()
        self._handlers[event_type].append(handler)
        if self._sub is None:
            async def dispatch(msg):
                event = HydraEvent.model_validate_json(msg.data)
                for h in (*self._handlers[event.type], *self._handlers[None]):
                    try:
                        await h(event)
                    except Exception:
                        log.exception("event handler failed")
                await msg.ack()

            from nats.js.api import DeliverPolicy
            self._sub = await self._js.subscribe(SUBJECTS, cb=dispatch, deliver_policy=DeliverPolicy.NEW)

    async def history(self, task_id: UUID) -> list[HydraEvent]:
        await self.connect()
        from nats.js.api import DeliverPolicy

        sub = await self._js.subscribe(f"hydra.events.{task_id}.>", ordered_consumer=True,
                                       deliver_policy=DeliverPolicy.ALL)
        events: list[HydraEvent] = []
        try:
            while True:
                try:
                    msg = await sub.next_msg(timeout=0.5)
                except Exception:
                    break
                events.append(HydraEvent.model_validate_json(msg.data))
        finally:
            await sub.unsubscribe()
        return events

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
