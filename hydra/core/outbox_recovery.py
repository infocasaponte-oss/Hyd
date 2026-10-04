# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.outbox_worker import OutboxWorker, WorkerResult


@dataclass(frozen=True)
class RecoveryResult:
    batches: int
    published: int
    retried: int
    dead_lettered: int


def recover_pending(
    worker: OutboxWorker,
    *,
    batch_size: int = 100,
    max_batches: int = 100,
) -> RecoveryResult:
    batches = 0
    published = 0
    retried = 0
    dead_lettered = 0

    while batches < max_batches:
        result: WorkerResult = worker.run_once(batch_size)
        batches += 1
        published += result.published
        retried += result.retried
        dead_lettered += result.dead_lettered

        if result.published == 0:
            break

    return RecoveryResult(
        batches=batches,
        published=published,
        retried=retried,
        dead_lettered=dead_lettered,
    )
