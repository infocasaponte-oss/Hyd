# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.provenance import ProvenanceLedger
from hydra.runtime.readiness import evaluate_readiness


def test_ready_when_core_dependencies_are_healthy(tmp_path):
    status = evaluate_readiness(
        outbox=TransactionalOutbox(tmp_path / "hydra.db"),
        events=JsonlEventStore(tmp_path / "events.jsonl"),
        provenance=ProvenanceLedger(tmp_path / "provenance.jsonl"),
        llm_healthy=True,
    )
    assert status.ready is True
    assert status.reasons == ()


def test_dead_letter_blocks_readiness(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    with outbox.transaction() as connection:
        message = outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={"event_type": "hydra.test"},
        )
    outbox.record_failure(
        message.id,
        error="boom",
        next_attempt_at=None,
        dead_letter=True,
    )
    status = evaluate_readiness(
        outbox=outbox,
        events=JsonlEventStore(tmp_path / "events.jsonl"),
        provenance=ProvenanceLedger(tmp_path / "provenance.jsonl"),
        llm_healthy=True,
    )
    assert status.ready is False
    assert "dead_letters_present" in status.reasons


def test_stopped_worker_blocks_readiness(tmp_path):
    status = evaluate_readiness(
        outbox=TransactionalOutbox(tmp_path / "hydra.db"),
        events=JsonlEventStore(tmp_path / "events.jsonl"),
        provenance=ProvenanceLedger(tmp_path / "provenance.jsonl"),
        llm_healthy=True,
        worker_running=False,
    )
    assert status.ready is False
    assert "outbox_worker_stopped" in status.reasons
