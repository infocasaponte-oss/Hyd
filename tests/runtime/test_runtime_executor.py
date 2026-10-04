# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import pytest
from hydra.core.inference_budget import inference_budget, ModelCallBudgetExceeded

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.runtime_evidence import RuntimeEvidenceStore
from hydra.runtime.runtime_executor import RuntimeExecutor
from hydra.runtime.runtime_health import RuntimeHealth
from hydra.runtime.traffic_router import TrafficRouter


def deployment(state: DeploymentState, generation: int) -> Deployment:
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path=f"{generation}.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )
    return Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=state,
        generation=generation,
    )


@pytest.mark.asyncio
async def test_one_call_budget_keeps_primary_and_skips_shadow():
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    registry.add(active)
    registry.add(deployment(DeploymentState.SHADOW, 2))
    calls = []

    async def call(variant_id, prompt, max_tokens):
        calls.append(variant_id)
        return "answer"

    health = RuntimeHealth()
    executor = RuntimeExecutor(TrafficRouter(registry, health), health, call)
    with inference_budget(1) as budget:
        result = await executor.execute(
            capability="reasoning.general", trace_id="trace", prompt="hi", max_tokens=64,
        )
    assert result.answer == "answer"
    assert result.shadow_variant_id is None
    assert calls == [str(active.variant_id)]
    assert budget.used == 1


@pytest.mark.asyncio
async def test_physical_and_logical_calls_share_budget():
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from hydra.registry.native import ModelRegistry
    from hydra.scheduler.native import ExecutionPlan, PlanStep, StepKind
    from hydra.scheduler.native_executor import Executor
    from hydra.verification.verifier import Verifier

    registry = DeploymentRegistry()
    registry.add(deployment(DeploymentState.ACTIVE, 1))

    async def call(*args):
        return "answer"

    health = RuntimeHealth()
    logical = AsyncMock()
    with inference_budget(1):
        await RuntimeExecutor(TrafficRouter(registry, health), health, call).execute(
            capability="reasoning.general", trace_id="trace", prompt="hi", max_tokens=64,
        )
        plan = ExecutionPlan(task_id=uuid4(), steps=[PlanStep(
            kind=StepKind.MODEL, capability="chat.multilingual", instruction="hello",
        )])
        with pytest.raises(ModelCallBudgetExceeded):
            await Executor(logical, ModelRegistry(), Verifier()).execute(plan, 64)
    logical.chat.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_primary", [False, True])
async def test_primary_failure_or_cancellation_cleans_up_shadow(cancel_primary):
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    shadow = deployment(DeploymentState.SHADOW, 2)
    registry.add(active)
    registry.add(shadow)
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def call(variant_id, prompt, max_tokens):
        if variant_id == str(shadow.variant_id):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        await started.wait()
        if cancel_primary:
            await asyncio.Event().wait()
        raise RuntimeError("primary failed")

    health = RuntimeHealth()
    executor = RuntimeExecutor(TrafficRouter(registry, health), health, call)
    task = asyncio.create_task(executor.execute(
        capability="reasoning.general", trace_id="trace", prompt="hello", max_tokens=64,
    ))
    await asyncio.wait_for(started.wait(), timeout=1)
    if cancel_primary:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel_primary else RuntimeError):
        await task
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_shadow_is_not_authoritative(tmp_path):
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    shadow = deployment(DeploymentState.SHADOW, 2)
    registry.add(active)
    registry.add(shadow)
    answers = {
        str(active.variant_id): "active-answer",
        str(shadow.variant_id): "shadow-answer",
    }

    async def call(variant_id: str, prompt: str, max_tokens: int) -> str:
        assert prompt == "hello"
        assert max_tokens == 64
        return answers[variant_id]

    health = RuntimeHealth()
    evidence = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    executor = RuntimeExecutor(
        TrafficRouter(registry, health),
        health,
        call,
        evidence,
    )
    result = await executor.execute(
        capability="reasoning.general",
        trace_id="trace",
        prompt="hello",
        max_tokens=64,
    )
    assert result.answer == "active-answer"
    assert result.shadow_answer == "shadow-answer"
    saved = (tmp_path / "evidence.jsonl").read_text()
    assert "active-answer" not in saved
    assert "shadow-answer" not in saved


@pytest.mark.asyncio
async def test_canary_failures_and_latency_are_recorded_as_evidence(tmp_path):
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    canary = deployment(DeploymentState.CANARY, 2)
    shadow = deployment(DeploymentState.SHADOW, 3)
    for item in (active, canary, shadow):
        registry.add(item)
    canary_id, shadow_id = str(canary.variant_id), str(shadow.variant_id)

    async def call(variant_id: str, prompt: str, max_tokens: int) -> str:
        if variant_id in (canary_id, shadow_id):
            raise RuntimeError("variant down")
        return "active-answer"

    health = RuntimeHealth()
    evidence = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    executor = RuntimeExecutor(TrafficRouter(registry, health, canary_percent=100), health, call, evidence)
    result = await executor.execute(capability="reasoning.general", trace_id="t", prompt="p", max_tokens=8)
    assert result.answer == "active-answer" and result.canary_variant_id == canary_id

    measured_canary = evidence.canary_evidence(canary_id)
    assert measured_canary.requests == 1 and measured_canary.error_rate == 1.0
    measured_shadow = evidence.shadow_evidence(shadow_id)
    assert measured_shadow.samples == 1 and measured_shadow.error_rate == 1.0
    record = next(evidence.records())
    assert record["canary_error"] is True and record["primary_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_canary_failure_is_recorded_even_when_the_fallback_fails(tmp_path):
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    canary = deployment(DeploymentState.CANARY, 2)
    registry.add(active)
    registry.add(canary)

    async def call(variant_id: str, prompt: str, max_tokens: int) -> str:
        raise RuntimeError("everything is down")

    health = RuntimeHealth()
    evidence = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    executor = RuntimeExecutor(TrafficRouter(registry, health, canary_percent=100), health, call, evidence)
    with pytest.raises(RuntimeError):
        await executor.execute(capability="reasoning.general", trace_id="t", prompt="p", max_tokens=8)
    measured = evidence.canary_evidence(str(canary.variant_id))
    assert measured.requests == 1 and measured.error_rate == 1.0


@pytest.mark.asyncio
async def test_exhausted_budget_does_not_blame_an_uncalled_fallback(tmp_path):
    registry = DeploymentRegistry()
    active = deployment(DeploymentState.ACTIVE, 1)
    canary = deployment(DeploymentState.CANARY, 2)
    registry.add(active)
    registry.add(canary)
    calls = []

    async def call(variant_id: str, prompt: str, max_tokens: int) -> str:
        calls.append(variant_id)
        raise RuntimeError("canary down")

    health = RuntimeHealth()
    evidence = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    executor = RuntimeExecutor(TrafficRouter(registry, health, canary_percent=100), health, call, evidence)
    with inference_budget(1), pytest.raises(ModelCallBudgetExceeded):
        await executor.execute(capability="reasoning.general", trace_id="t", prompt="p", max_tokens=8)
    assert calls == [str(canary.variant_id)]  # the active variant was never invoked
    record = next(evidence.records())
    assert record["canary_error"] is True
    assert record["primary_error"] is None  # unknown, not failed
