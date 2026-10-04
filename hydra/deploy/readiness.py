# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.durable_events import JsonlEventStore
from hydra.core.outbox import TransactionalOutbox
from hydra.core.outbox_metrics import collect_outbox_metrics
from hydra.provenance.ledger import ProvenanceLedger


@dataclass(frozen=True)
class ReadinessStatus:
    ready: bool
    reasons: tuple[str, ...]
    pending_outbox: int
    dead_letters: int
    events_integrity: bool
    provenance_integrity: bool
    llm_healthy: bool
    worker_running: bool
    oldest_pending_age_seconds: float | None


def evaluate_readiness(
    *,
    outbox: TransactionalOutbox,
    events: JsonlEventStore,
    provenance: ProvenanceLedger,
    llm_healthy: bool,
    worker_running: bool = True,
    max_pending: int = 1000,
    max_oldest_pending_age_seconds: float = 300.0,
) -> ReadinessStatus:
    metrics = collect_outbox_metrics(outbox)
    event_report = events.verify_integrity()
    provenance_report = provenance.verify_integrity()

    reasons: list[str] = []
    if not llm_healthy:
        reasons.append("llm_unhealthy")
    if not worker_running:
        reasons.append("outbox_worker_stopped")
    if not event_report.valid:
        reasons.append("event_integrity_failed")
    if not provenance_report.valid:
        reasons.append("provenance_integrity_failed")
    if metrics.dead_letters:
        reasons.append("dead_letters_present")
    if metrics.pending > max_pending:
        reasons.append("outbox_backlog_exceeded")
    if (
        metrics.oldest_pending_age_seconds is not None
        and metrics.oldest_pending_age_seconds > max_oldest_pending_age_seconds
    ):
        reasons.append("outbox_backlog_stalled")

    return ReadinessStatus(
        ready=not reasons,
        reasons=tuple(reasons),
        pending_outbox=metrics.pending,
        dead_letters=metrics.dead_letters,
        events_integrity=event_report.valid,
        provenance_integrity=provenance_report.valid,
        llm_healthy=llm_healthy,
        worker_running=worker_running,
        oldest_pending_age_seconds=metrics.oldest_pending_age_seconds,
    )
