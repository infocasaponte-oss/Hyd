# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.outbox_dispatcher import OutboxDispatcher
from hydra.runtime.outbox_worker import OutboxWorker
from hydra.runtime.provenance import ProvenanceLedger
from hydra.runtime.startup_recovery import recover_pending


def test_startup_recovery_drains_pending_messages(tmp_path):
    path = tmp_path / "hydra.db"
    outbox = TransactionalOutbox(path)
    task_id = uuid4()
    with outbox.transaction() as connection:
        for index in range(3):
            outbox.enqueue(
                connection,
                topic="event",
                aggregate_id=task_id,
                trace_id="trace",
                payload={
                    "event_type": f"hydra.test.{index}",
                    "payload": {"index": index},
                },
            )

    worker = OutboxWorker(
        TransactionalOutbox(path),
        OutboxDispatcher(
            TransactionalOutbox(path),
            JsonlEventStore(tmp_path / "events.jsonl"),
            ProvenanceLedger(tmp_path / "provenance.jsonl"),
        ),
    )
    recovered = recover_pending(worker, batch_size=2)

    assert recovered.published == 3
    assert TransactionalOutbox(path).pending() == []
