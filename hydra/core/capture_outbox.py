# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Durable retry for capture writes, on the HYDRA-SO transactional outbox.

The CapturePipeline writes inline and never fails a user request. When a ledger or corpus
write fails, the write is deferred to this outbox instead of being lost: the runtime
``OutboxWorker`` retries it with exponential backoff and moves it to the dead-letter queue
after ``max_attempts`` (at-least-once delivery; corpus ingestion deduplicates).

The messages live in a local SQLite file, or in the PostgreSQL table ``capture_outbox``
(HYDRA_OUTBOX_BACKEND, ``hydra.core.capture_outbox_pg``) shared by every node, where each
worker claims what it retries so no deferred write is replayed by two nodes at once."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from hydra.core.outbox import OutboxMessage, TransactionalOutbox
from hydra.core.outbox_dispatch import TopicDispatcher
from hydra.core.outbox_worker import OutboxWorker, RetryPolicy, WorkerResult

log = logging.getLogger("hydra.capture")

LEDGER = "capture.ledger"
CORPUS = "capture.corpus"


class CaptureDispatcher(TopicDispatcher):
    """Replays deferred capture writes (duck-typed ``OutboxDispatcher`` for ``OutboxWorker``)."""

    def __init__(self, ledger=None, corpus=None) -> None:
        self.ledger = ledger
        self.corpus = corpus
        super().__init__(
            {LEDGER: self._ledger, CORPUS: self._corpus},
            unknown_topic_prefix="Unknown capture outbox topic",
        )

    def _ledger(self, message: OutboxMessage) -> None:
        payload = message.payload
        if self.ledger is None:
            raise RuntimeError("ledger is not configured")
        self.ledger.append(payload["event_type"], payload["payload"], **payload.get("options", {}))
        return
    def _corpus(self, message: OutboxMessage) -> None:
        payload = message.payload
        if self.corpus is None:
            raise RuntimeError("corpus is not configured")
        from hydra.corpus.records import CorpusRecord

        self.corpus.ingest(CorpusRecord.model_validate(payload["record"]))
        return


def _aggregate(task_id: str) -> UUID:
    try:
        return UUID(task_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"hydra:task:{task_id}")


class CaptureOutbox:
    def __init__(self, path: Path, *, ledger=None, corpus=None, policy: RetryPolicy | None = None,
                 store=None) -> None:
        """``store``: a ``PostgresOutbox`` (or any store with the ``TransactionalOutbox`` interface);
        default, the SQLite outbox at ``path``."""
        self.outbox = store if store is not None else TransactionalOutbox(path)
        self.worker = OutboxWorker(self.outbox, CaptureDispatcher(ledger, corpus), policy)

    def defer(self, topic: str, task_id: str, payload: dict[str, Any], trace_id: str = "") -> None:
        with self.outbox.transaction() as connection:
            self.outbox.enqueue(connection, topic=topic, aggregate_id=_aggregate(task_id),
                                trace_id=trace_id or task_id, payload=payload)
        log.warning("capture write deferred to outbox", extra={"topic": topic, "task": task_id})

    def drain(self, limit: int = 100) -> WorkerResult:
        return self.worker.run_once(limit)

    def stats(self) -> dict[str, Any]:
        return self.outbox.counts()  # counting must not claim messages (PostgreSQL pending() does)

    def dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        return [{**asdict(m), "id": str(m.id), "aggregate_id": str(m.aggregate_id)}
                for m in self.outbox.dead_letters(limit)]
