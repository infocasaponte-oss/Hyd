# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.outbox_dispatch import TopicDispatcher
from hydra.corpus.artifact_candidates import CorpusRecord, CorpusStore
from hydra.core.durable_events import JsonlEventStore
from hydra.core.outbox import OutboxMessage, TransactionalOutbox
from hydra.provenance.ledger import ProvenanceLedger, ProvenanceRecord


@dataclass(frozen=True)
class DispatchResult:
    published: int
    failed: int


class OutboxDispatcher(TopicDispatcher):
    def __init__(
        self,
        outbox: TransactionalOutbox,
        events: JsonlEventStore,
        provenance: ProvenanceLedger,
        corpus: CorpusStore | None = None,
    ):
        self.outbox = outbox
        self.events = events
        self.provenance = provenance
        self.corpus = corpus
        super().__init__({
            "event": self._event,
            "provenance": self._provenance,
            "corpus": self._corpus,
        })

    def dispatch_once(self, limit: int = 100) -> DispatchResult:
        published = 0
        failed = 0
        for message in self.outbox.pending(limit):
            try:
                self._dispatch(message)
            except Exception:  # noqa: BLE001
                failed += 1
                continue
            self.outbox.mark_published(message.id)
            published += 1
        return DispatchResult(published=published, failed=failed)

    def _event(self, message: OutboxMessage) -> None:
        payload = message.payload
        self.events.append(
            event_type=payload["event_type"],
            aggregate_id=message.aggregate_id,
            producer=payload.get("producer", "hydra.outbox"),
            trace_id=message.trace_id,
            payload=payload.get("payload", {}),
            source_message_id=message.id,
        )
        return

    def _provenance(self, message: OutboxMessage) -> None:
        payload = message.payload
        self.provenance.append(
            ProvenanceRecord(
                task_id=message.aggregate_id,
                trace_id=message.trace_id,
                action=payload["action"],
                inputs=payload.get("inputs", {}),
                outputs=payload.get("outputs", {}),
                source_message_id=message.id,
            )
        )
        return

    def _corpus(self, message: OutboxMessage) -> None:
        if self.corpus is None:
            raise RuntimeError("Corpus store is not configured")
        record = CorpusRecord.model_validate(message.payload)
        self.corpus.append_once(record)
        return
