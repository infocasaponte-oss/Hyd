# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.outbox_dispatcher import OutboxDispatcher
from hydra.runtime.outbox_worker import OutboxWorker, RetryPolicy
from hydra.runtime.provenance import ProvenanceLedger


def test_worker_retries_then_dead_letters_unknown_topic(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    with outbox.transaction() as connection:
        message = outbox.enqueue(
            connection,
            topic="unknown",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={},
        )

    dispatcher = OutboxDispatcher(
        outbox,
        JsonlEventStore(tmp_path / "events.jsonl"),
        ProvenanceLedger(tmp_path / "provenance.jsonl"),
    )
    worker = OutboxWorker(
        outbox,
        dispatcher,
        RetryPolicy(max_attempts=2, base_delay_seconds=0),
    )

    first = worker.run_once()
    assert first.retried == 1
    assert outbox.pending()[0].attempts == 1

    second = worker.run_once()
    assert second.dead_lettered == 1
    assert outbox.pending() == []
    dead = outbox.dead_letters()
    assert len(dead) == 1
    assert dead[0].id == message.id
    assert dead[0].attempts == 2


def test_worker_publishes_valid_message(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    task_id = uuid4()
    with outbox.transaction() as connection:
        outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=task_id,
            trace_id="trace",
            payload={"event_type": "hydra.test", "payload": {"ok": True}},
        )

    events = JsonlEventStore(tmp_path / "events.jsonl")
    worker = OutboxWorker(
        outbox,
        OutboxDispatcher(
            outbox,
            events,
            ProvenanceLedger(tmp_path / "provenance.jsonl"),
        ),
    )

    result = worker.run_once()
    assert result.published == 1
    assert outbox.pending() == []
    assert events.for_aggregate(task_id)[0].event_type == "hydra.test"
