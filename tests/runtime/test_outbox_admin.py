# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.outbox import TransactionalOutbox


def test_dead_letter_can_be_requeued(tmp_path):
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
    assert len(outbox.dead_letters()) == 1

    assert outbox.requeue_dead_letter(message.id) is True
    assert outbox.dead_letters() == []
    pending = outbox.pending()
    assert len(pending) == 1
    assert pending[0].attempts == 0
    assert pending[0].last_error is None
