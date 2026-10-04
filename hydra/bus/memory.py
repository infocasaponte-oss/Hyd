# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from hydra.bus.base import EventBus, EventHandler
from hydra.core.events import EventType, HydraEvent

log = logging.getLogger("hydra.bus")


class InMemoryEventBus(EventBus):
    def __init__(self, max_tasks: int = 1000) -> None:
        self._handlers: dict[EventType | None, list[EventHandler]] = defaultdict(list)
        self._log: dict[UUID, list[HydraEvent]] = {}
        self._max_tasks = max_tasks

    async def publish(self, event: HydraEvent) -> None:
        if event.task_id not in self._log and len(self._log) >= self._max_tasks:
            self._log.pop(next(iter(self._log)))
        self._log.setdefault(event.task_id, []).append(event)
        for handler in (*self._handlers[event.type], *self._handlers[None]):
            try:
                await handler(event)
            except Exception:  # a broken subscriber must never break the kernel
                log.exception("event handler failed for %s", event.type.value)

    async def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def history(self, task_id: UUID) -> list[HydraEvent]:
        return list(self._log.get(task_id, []))
