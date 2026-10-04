# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.durable_events import JsonlEventStore


@dataclass
class RuntimeEventEmitter:
    store: JsonlEventStore

    def model_selected(
        self,
        *,
        aggregate_id,
        trace_id: str,
        capability: str,
        variant_id: str,
        state: str,
    ) -> None:
        self.store.append(
            event_type="hydra.model.selected",
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            producer="hydra.runtime",
            payload={
                "capability": capability,
                "variant_id": variant_id,
                "deployment_state": state,
            },
        )

    def failover(
        self,
        *,
        aggregate_id,
        trace_id: str,
        from_variant_id: str,
        to_variant_id: str,
        reason: str,
    ) -> None:
        self.store.append(
            event_type="hydra.runtime.failover",
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            producer="hydra.runtime",
            payload={
                "from_variant_id": from_variant_id,
                "to_variant_id": to_variant_id,
                "reason": reason,
            },
        )

    def shadow_compared(
        self,
        *,
        aggregate_id,
        trace_id: str,
        primary_variant_id: str,
        shadow_variant_id: str,
        agreement: bool | None,
    ) -> None:
        self.store.append(
            event_type="hydra.shadow.compared",
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            producer="hydra.runtime",
            payload={
                "primary_variant_id": primary_variant_id,
                "shadow_variant_id": shadow_variant_id,
                "exact_agreement": agreement,
            },
        )

    def circuit_opened(
        self,
        *,
        aggregate_id,
        trace_id: str,
        variant_id: str,
    ) -> None:
        self.store.append(
            event_type="hydra.circuit.opened",
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            producer="hydra.runtime",
            payload={"variant_id": variant_id},
        )
