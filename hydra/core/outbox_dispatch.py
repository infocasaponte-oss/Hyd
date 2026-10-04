# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Shared topic routing; adapters retain their own payload contracts and effects."""
from collections.abc import Callable, Mapping
from typing import Protocol

from hydra.core.outbox import OutboxMessage


class MessageDispatcher(Protocol):
    def _dispatch(self, message: OutboxMessage) -> None: ...


class TopicDispatcher:
    def __init__(
        self,
        handlers: Mapping[str, Callable[[OutboxMessage], None]],
        *,
        unknown_topic_prefix: str = "Unknown outbox topic",
    ) -> None:
        self._handlers = dict(handlers)
        self._unknown_topic_prefix = unknown_topic_prefix

    def _dispatch(self, message: OutboxMessage) -> None:
        handler = self._handlers.get(message.topic)
        if handler is None:
            raise ValueError(f"{self._unknown_topic_prefix}: {message.topic}")
        handler(message)
