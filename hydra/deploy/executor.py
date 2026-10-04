# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from contextlib import suppress

from hydra.core.inference_budget import ModelCallBudgetExceeded, reserve_model_call
from hydra.deploy.runtime_evidence import RuntimeEvidenceStore
from hydra.deploy.runtime_health import RuntimeHealth
from hydra.deploy.traffic_router import TrafficDecision, TrafficRouter

InferenceCall = Callable[[str, str, int], Awaitable[str]]


@dataclass(frozen=True)
class RuntimeExecution:
    answer: str
    primary_variant_id: str
    shadow_variant_id: str | None = None
    shadow_answer: str | None = None
    canary_variant_id: str | None = None


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


class RuntimeExecutor:
    def __init__(
        self,
        router: TrafficRouter,
        health: RuntimeHealth,
        inference_call: InferenceCall,
        evidence_store: RuntimeEvidenceStore | None = None,
    ):
        self.router = router
        self.health = health
        self.inference_call = inference_call
        self.evidence_store = evidence_store

    async def execute(
        self,
        *,
        capability: str,
        trace_id: str,
        prompt: str,
        max_tokens: int,
    ) -> RuntimeExecution:
        decision = self.router.route(capability, trace_id)
        primary = decision.canary or decision.primary
        primary_id = str(primary.variant_id)
        canary_id = str(decision.canary.variant_id) if decision.canary else None
        canary_error: bool | None = None
        canary_latency_ms: float | None = None
        reserve_model_call()
        shadow_task = self._start_shadow(decision, prompt, max_tokens)
        try:
            started = time.perf_counter()
            try:
                answer = await self.inference_call(primary_id, prompt, max_tokens)
            except Exception:
                self.health.failure(primary_id)
                if primary is decision.canary:
                    canary_error = True  # the canary failed this request; the active variant answers it
                    started = time.perf_counter()
                    try:
                        answer, primary_id = await self._fallback(decision, prompt, max_tokens)
                    except Exception as exc:
                        # The request fails, but the canary failure is still evidence: without this
                        # record a canary that fails together with its fallback would look error-free.
                        if shadow_task is not None:
                            shadow_task.cancel()
                        if self.evidence_store is not None:
                            # Budget exhausted before the fallback call: the active variant was
                            # never invoked, so its outcome is unknown, not a failure.
                            fallback_called = not isinstance(exc, ModelCallBudgetExceeded)
                            self.evidence_store.append(
                                trace_id=trace_id,
                                capability=capability,
                                primary_variant_id=str(decision.primary.variant_id),
                                primary_output="",
                                primary_error=True if fallback_called else None,
                                canary_variant_id=canary_id,
                                canary_error=True,
                            )
                        raise
                else:
                    raise
            else:
                self.health.success(primary_id)
                if primary is decision.canary:
                    canary_error = False
                    canary_latency_ms = _elapsed_ms(started)
            primary_latency_ms = _elapsed_ms(started)

            shadow_id = None
            shadow_answer = None
            shadow_error: bool | None = None
            shadow_latency_ms: float | None = None
            if shadow_task is not None:
                shadow_id = str(decision.shadow.variant_id) if decision.shadow else None
                try:
                    shadow_answer, shadow_latency_ms = await shadow_task
                    shadow_error = False
                    if shadow_id:
                        self.health.success(shadow_id)
                except Exception:  # noqa: BLE001
                    shadow_error = True
                    if shadow_id:
                        self.health.failure(shadow_id)

            if self.evidence_store is not None:
                self.evidence_store.append(
                    trace_id=trace_id,
                    capability=capability,
                    primary_variant_id=primary_id,
                    primary_output=answer,
                    shadow_variant_id=shadow_id,
                    shadow_output=shadow_answer,
                    primary_latency_ms=primary_latency_ms,
                    shadow_error=shadow_error,
                    shadow_latency_ms=shadow_latency_ms,
                    canary_variant_id=canary_id,
                    canary_error=canary_error,
                    canary_latency_ms=canary_latency_ms,
                )

            return RuntimeExecution(
                answer=answer,
                primary_variant_id=primary_id,
                shadow_variant_id=shadow_id,
                shadow_answer=shadow_answer,
                canary_variant_id=canary_id,
            )
        finally:
            if shadow_task is not None:
                if not shadow_task.done():
                    shadow_task.cancel()
                # Retrieve failures too, including when primary inference failed first.
                with suppress(asyncio.CancelledError, Exception):
                    await shadow_task

    def _start_shadow(
        self,
        decision: TrafficDecision,
        prompt: str,
        max_tokens: int,
    ) -> asyncio.Task[tuple[str, float]] | None:
        if decision.shadow is None or not reserve_model_call(optional=True):
            return None
        shadow_id = str(decision.shadow.variant_id)

        async def timed() -> tuple[str, float]:
            started = time.perf_counter()
            answer = await self.inference_call(shadow_id, prompt, max_tokens)
            return answer, _elapsed_ms(started)

        return asyncio.create_task(timed())

    async def _fallback(
        self,
        decision: TrafficDecision,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, str]:
        fallback_id = str(decision.primary.variant_id)
        reserve_model_call()
        try:
            answer = await self.inference_call(fallback_id, prompt, max_tokens)
        except Exception:
            self.health.failure(fallback_id)
            raise
        self.health.success(fallback_id)
        return answer, fallback_id
