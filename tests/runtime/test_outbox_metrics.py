# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.outbox import TransactionalOutbox
from hydra.runtime.outbox_metrics import collect_outbox_metrics


def test_metrics_count_pending_and_dead_letters(tmp_path):
    outbox = TransactionalOutbox(tmp_path / "hydra.db")
    with outbox.transaction() as connection:
        message = outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={"event_type": "hydra.test"},
        )

    metrics = collect_outbox_metrics(outbox)
    assert metrics.pending == 1
    assert metrics.dead_letters == 0
    assert metrics.oldest_pending_age_seconds is not None
    assert metrics.oldest_pending_age_seconds >= 0

    outbox.record_failure(
        message.id,
        error="boom",
        next_attempt_at=None,
        dead_letter=True,
    )
    metrics = collect_outbox_metrics(outbox)
    assert metrics.pending == 0
    assert metrics.dead_letters == 1
    assert metrics.oldest_pending_age_seconds is None
