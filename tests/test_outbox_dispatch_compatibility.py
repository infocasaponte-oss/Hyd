# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib
from uuid import uuid4

import pytest

from hydra.core.capture_outbox import CaptureDispatcher
from hydra.core.durable_events import JsonlEventStore
from hydra.core.outbox import TransactionalOutbox
from hydra.core.outbox_worker import OutboxWorker, RetryPolicy
from hydra.provenance.ledger import ProvenanceLedger
from hydra.runtime.outbox_dispatcher import OutboxDispatcher


def test_worker_legacy_module_is_canonical():
    assert importlib.import_module("hydra.runtime.outbox_worker") is importlib.import_module(
        "hydra.core.outbox_worker"
    )


@pytest.mark.parametrize("kind", ["capture", "runtime"])
def test_unregistered_topic_retains_error_and_dead_letter_behavior(tmp_path, kind):
    store = TransactionalOutbox(tmp_path / "outbox.db")
    dispatcher = CaptureDispatcher() if kind == "capture" else OutboxDispatcher(
        store, JsonlEventStore(tmp_path / "events.jsonl"),
        ProvenanceLedger(tmp_path / "provenance.jsonl"),
    )
    with store.transaction() as connection:
        message = store.enqueue(connection, topic="unknown", aggregate_id=uuid4(),
                                trace_id="trace", payload={})
    expected = "Unknown capture outbox topic: unknown" if kind == "capture" else "Unknown outbox topic: unknown"
    with pytest.raises(ValueError) as error:
        dispatcher._dispatch(message)
    assert str(error.value) == expected
    worker = OutboxWorker(store, dispatcher, RetryPolicy(max_attempts=2, base_delay_seconds=0))
    assert worker.run_once().retried == 1
    assert worker.run_once().dead_lettered == 1
    [dead] = store.dead_letters()
    assert dead.id == message.id
    assert dead.attempts == 2
    assert dead.last_error == expected


def test_capture_missing_corpus_retains_failure(tmp_path):
    store = TransactionalOutbox(tmp_path / "outbox.db")
    with store.transaction() as connection:
        message = store.enqueue(connection, topic="capture.corpus", aggregate_id=uuid4(),
                                trace_id="trace", payload={})
    with pytest.raises(RuntimeError, match="^corpus is not configured$"):
        CaptureDispatcher()._dispatch(message)
