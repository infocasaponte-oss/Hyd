# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Operating metrics of the runtime line: outbox backlog, cognitive spans and deployments by state."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from hydra.deploy.deployment_registry import DeploymentRegistry
from hydra.core.outbox import TransactionalOutbox
from hydra.core.outbox_metrics import collect_outbox_metrics
from hydra.core.runtime_paths import runtime_path


@dataclass(frozen=True)
class OperatingMetrics:
    outbox_pending: int
    outbox_dead_letters: int
    oldest_pending_age_seconds: float | None
    spans_total: int
    spans_error: int
    avg_span_duration_ms: float | None
    spans_by_name: dict[str, int]
    deployments_by_state: dict[str, int]


def collect_operating_metrics(
    *,
    outbox: TransactionalOutbox,
    trace_path: str | Path = runtime_path("traces.jsonl"),
    deployments: DeploymentRegistry | None = None,
    max_trace_records: int = 10_000,
    traces=None,
) -> OperatingMetrics:
    """``traces``: a store with ``recent(limit)`` (the kernel's trace store, cluster-wide on PostgreSQL);
    without it, the spans are read from ``trace_path``."""
    outbox_metrics = collect_outbox_metrics(outbox)
    if traces is None:
        from hydra.observability.spans import TraceStore

        traces = TraceStore(trace_path)
    records: list[dict] = traces.recent(max_trace_records)

    durations = [
        float(record["duration_ms"])
        for record in records
        if record.get("duration_ms") is not None
    ]
    names = Counter(str(record.get("name", "unknown")) for record in records)
    deployment_states: Counter[str] = Counter()
    if deployments is not None:
        deployment_states.update(
            item.state.value for item in deployments.deployments.values()
        )

    return OperatingMetrics(
        outbox_pending=outbox_metrics.pending,
        outbox_dead_letters=outbox_metrics.dead_letters,
        oldest_pending_age_seconds=outbox_metrics.oldest_pending_age_seconds,
        spans_total=len(records),
        spans_error=sum(record.get("status") == "error" for record in records),
        avg_span_duration_ms=(
            sum(durations) / len(durations) if durations else None
        ),
        spans_by_name=dict(sorted(names.items())),
        deployments_by_state=dict(sorted(deployment_states.items())),
    )
