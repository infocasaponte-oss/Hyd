# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.outbox_dispatcher import OutboxDispatcher
from hydra.runtime.provenance import ProvenanceLedger


def test_dispatcher_materializes_event_and_provenance(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    task_id = uuid4()
    with outbox.transaction() as connection:
        outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=task_id,
            trace_id="trace",
            payload={
                "event_type": "hydra.task.completed",
                "payload": {"ok": True},
            },
        )
        outbox.enqueue(
            connection,
            topic="provenance",
            aggregate_id=task_id,
            trace_id="trace",
            payload={"action": "task.completed"},
        )

    events = JsonlEventStore(tmp_path / "events.jsonl")
    provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")
    result = OutboxDispatcher(outbox, events, provenance).dispatch_once()

    assert result.published == 2
    assert result.failed == 0
    assert outbox.pending() == []
    assert events.verify_integrity().valid is True
    assert provenance.verify_integrity().valid is True
