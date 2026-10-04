# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.contracts import HydraTask, TaskStatus
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.kernel import HydraKernel
from hydra.runtime.runtime_bridge import RuntimeBridge
from hydra.runtime.runtime_events import RuntimeEventEmitter
from hydra.runtime.runtime_executor import RuntimeExecutor
from hydra.runtime.runtime_health import RuntimeHealth
from hydra.runtime.traffic_router import TrafficRouter


class LogicalLLM:
    async def chat(self, messages, *, temperature=0.2, max_tokens=1024):
        return "logical-answer"


@pytest.mark.asyncio
async def test_kernel_falls_back_when_no_physical_deployment(tmp_path):
    registry = DeploymentRegistry()
    health = RuntimeHealth()

    async def physical_call(variant_id: str, prompt: str, max_tokens: int) -> str:
        raise AssertionError("physical inference must not run without deployment")

    events = JsonlEventStore(tmp_path / "events.jsonl")
    bridge = RuntimeBridge(
        RuntimeExecutor(
            TrafficRouter(registry, health),
            health,
            physical_call,
        ),
        health,
        RuntimeEventEmitter(events),
    )
    kernel = HydraKernel(events=events, runtime_bridge=bridge)
    task = HydraTask(goal="hello")

    result = await kernel.run(task, LogicalLLM())

    assert result.status == TaskStatus.COMPLETED
    assert result.answer == "logical-answer"
    names = [event.event_type for event in events.for_aggregate(task.id)]
    assert "hydra.runtime.logical_fallback" in names
    assert "hydra.task.completed" in names
