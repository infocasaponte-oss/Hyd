# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.outbox import TransactionalOutbox


def test_outbox_commit_persists_message(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    with outbox.transaction() as connection:
        outbox.enqueue(
            connection,
            topic="hydra.task.completed",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={"ok": True},
        )
    pending = outbox.pending()
    assert len(pending) == 1
    assert pending[0].payload == {"ok": True}


def test_outbox_rollback_is_atomic(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    with pytest.raises(RuntimeError), outbox.transaction() as connection:
        outbox.enqueue(
            connection,
            topic="hydra.task.completed",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={"ok": True},
        )
        raise RuntimeError("boom")
    assert outbox.pending() == []


def test_outbox_preserves_insertion_order_when_timestamps_tie(tmp_path, monkeypatch):
    import hydra.runtime.outbox as outbox_module

    frozen = outbox_module.datetime(2026, 1, 1, tzinfo=outbox_module.UTC)

    class FrozenDatetime(outbox_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(outbox_module, "datetime", FrozenDatetime)
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    topics = [f"topic-{index}" for index in range(25)]
    with outbox.transaction() as connection:
        for topic in topics:
            outbox.enqueue(connection, topic=topic, aggregate_id=uuid4(), trace_id="t", payload={})

    assert [message.topic for message in outbox.pending()] == topics
