# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hydra.registry.circuit_breaker import CircuitState
from hydra.deploy.events import RuntimeEventEmitter
from hydra.deploy.executor import RuntimeExecution, RuntimeExecutor
from hydra.deploy.runtime_health import RuntimeHealth


@dataclass
class RuntimeBridge:
    executor: RuntimeExecutor
    health: RuntimeHealth
    events: RuntimeEventEmitter

    async def execute(
        self,
        *,
        task_id: UUID,
        trace_id: str,
        capability: str,
        prompt: str,
        max_tokens: int,
    ) -> RuntimeExecution:
        decision = self.executor.router.route(capability, trace_id)
        selected = decision.canary or decision.primary
        selected_id = str(selected.variant_id)
        self.events.model_selected(
            aggregate_id=task_id,
            trace_id=trace_id,
            capability=capability,
            variant_id=selected_id,
            state=selected.state.value,
        )
        before = self.health.breaker_for(selected_id).state
        result = await self.executor.execute(
            capability=capability,
            trace_id=trace_id,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        if result.primary_variant_id != selected_id:
            self.events.failover(
                aggregate_id=task_id,
                trace_id=trace_id,
                from_variant_id=selected_id,
                to_variant_id=result.primary_variant_id,
                reason="runtime_failure",
            )
        after = self.health.breaker_for(selected_id).state
        if before != CircuitState.OPEN and after == CircuitState.OPEN:
            self.events.circuit_opened(
                aggregate_id=task_id,
                trace_id=trace_id,
                variant_id=selected_id,
            )
        if result.shadow_variant_id is not None:
            agreement = (
                result.answer == result.shadow_answer
                if result.shadow_answer is not None
                else None
            )
            self.events.shadow_compared(
                aggregate_id=task_id,
                trace_id=trace_id,
                primary_variant_id=result.primary_variant_id,
                shadow_variant_id=result.shadow_variant_id,
                agreement=agreement,
            )
        return result
