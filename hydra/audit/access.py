# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from hydra.core.durable_events import JsonlEventStore


@dataclass
class SecurityAudit:
    events: JsonlEventStore

    def record(
        self,
        *,
        event_type: str,
        endpoint: str,
        outcome: str,
        identity_hash: str | None = None,
        trace_id: str | None = None,
        aggregate_id: UUID | None = None,
    ) -> None:
        self.events.append(
            event_type=event_type,
            aggregate_id=aggregate_id or uuid4(),
            producer="hydra.security",
            trace_id=trace_id or uuid4().hex,
            payload={
                "endpoint": endpoint,
                "outcome": outcome,
                "identity_hash": identity_hash,
            },
        )
