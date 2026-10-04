# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from hydra.core.outbox import TransactionalOutbox


@dataclass(frozen=True)
class OutboxMetrics:
    pending: int
    dead_letters: int
    oldest_pending_age_seconds: float | None


def collect_outbox_metrics(outbox: TransactionalOutbox) -> OutboxMetrics:
    """Counted by the store (``pending_summary``): no row is loaded, and on PostgreSQL no message is
    claimed, which ``pending()`` would do."""
    pending, dead_letters, oldest = outbox.pending_summary()
    oldest_age = None
    if oldest is not None:
        oldest_age = max((datetime.now(UTC) - datetime.fromisoformat(oldest)).total_seconds(), 0.0)
    return OutboxMetrics(
        pending=pending,
        dead_letters=dead_letters,
        oldest_pending_age_seconds=oldest_age,
    )
