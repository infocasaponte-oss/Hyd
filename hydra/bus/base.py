# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Abstract event bus. Dev: in-memory. Production: Redis Streams (later NATS)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from uuid import UUID

from hydra.core.events import EventType, HydraEvent

EventHandler = Callable[[HydraEvent], Awaitable[None]]


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event: HydraEvent) -> None: ...

    @abstractmethod
    async def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None:
        """Subscribe to one event type, or to every event with ``None``."""

    @abstractmethod
    async def history(self, task_id: UUID) -> list[HydraEvent]:
        """Every event of a task, in order. Enables replay(task_id)."""

    async def close(self) -> None:
        return None
