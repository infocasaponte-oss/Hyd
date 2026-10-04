# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.corpus import CorpusGate, CorpusRecord, CorpusStore
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.outbox_dispatcher import OutboxDispatcher
from hydra.runtime.provenance import ProvenanceLedger


def test_dispatch_retry_does_not_duplicate_event_or_provenance(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    task_id = uuid4()
    with outbox.transaction() as connection:
        event = outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=task_id,
            trace_id="trace",
            payload={"event_type": "hydra.test", "payload": {"x": 1}},
        )
        provenance = outbox.enqueue(
            connection,
            topic="provenance",
            aggregate_id=task_id,
            trace_id="trace",
            payload={"action": "test"},
        )

    events = JsonlEventStore(tmp_path / "events.jsonl")
    ledger = ProvenanceLedger(tmp_path / "provenance.jsonl")
    dispatcher = OutboxDispatcher(outbox, events, ledger)

    dispatcher._dispatch(event)
    dispatcher._dispatch(event)
    dispatcher._dispatch(provenance)
    dispatcher._dispatch(provenance)

    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1
    assert len((tmp_path / "provenance.jsonl").read_text().splitlines()) == 1


def test_corpus_dispatch_is_persistent_and_deduplicated(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    record = CorpusGate().evaluate(
        CorpusRecord(
            task_id=uuid4(),
            belief_id=uuid4(),
            artifact_hashes=["a" * 64],
        )
    )
    with outbox.transaction() as connection:
        message = outbox.enqueue(
            connection,
            topic="corpus",
            aggregate_id=record.task_id,
            trace_id="trace",
            payload=record.model_dump(mode="json"),
        )

    store = CorpusStore(tmp_path / "corpus.jsonl")
    dispatcher = OutboxDispatcher(
        outbox,
        JsonlEventStore(tmp_path / "events.jsonl"),
        ProvenanceLedger(tmp_path / "provenance.jsonl"),
        store,
    )
    dispatcher._dispatch(message)
    dispatcher._dispatch(message)

    assert len((tmp_path / "corpus.jsonl").read_text().splitlines()) == 1
