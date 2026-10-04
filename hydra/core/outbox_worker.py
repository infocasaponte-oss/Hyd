# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hydra.core.outbox import TransactionalOutbox
from hydra.core.outbox_dispatch import MessageDispatcher


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    def delay_for(self, attempts_so_far: int) -> float:
        delay = self.base_delay_seconds * (2 ** max(attempts_so_far, 0))
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True)
class WorkerResult:
    published: int
    retried: int
    dead_lettered: int


class OutboxWorker:
    def __init__(
        self,
        outbox: TransactionalOutbox,
        dispatcher: MessageDispatcher,
        policy: RetryPolicy | None = None,
    ):
        self.outbox = outbox
        self.dispatcher = dispatcher
        self.policy = policy or RetryPolicy()

    def run_once(self, limit: int = 100) -> WorkerResult:
        published = 0
        retried = 0
        dead_lettered = 0
        for message in self.outbox.pending(limit):
            try:
                self.dispatcher._dispatch(message)
            except Exception as exc:  # noqa: BLE001
                next_attempt_number = message.attempts + 1
                dead = next_attempt_number >= self.policy.max_attempts
                next_attempt_at = None
                if not dead:
                    delay = self.policy.delay_for(message.attempts)
                    next_attempt_at = (
                        datetime.now(UTC) + timedelta(seconds=delay)
                    ).isoformat()
                self.outbox.record_failure(
                    message.id,
                    error=str(exc),
                    next_attempt_at=next_attempt_at,
                    dead_letter=dead,
                )
                if dead:
                    dead_lettered += 1
                else:
                    retried += 1
                continue

            self.outbox.mark_published(message.id)
            published += 1

        return WorkerResult(
            published=published,
            retried=retried,
            dead_lettered=dead_lettered,
        )

    async def run_forever(
        self,
        *,
        poll_seconds: float = 1.0,
        batch_size: int = 100,
    ) -> None:
        while True:
            self.run_once(batch_size)
            await asyncio.sleep(poll_seconds)
