# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.contracts import HydraTask, TaskStatus
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.kernel import HydraKernel


class FakeLLM:
    async def chat(self, messages, *, temperature=0.2, max_tokens=1024):
        return "HYDRA local test response"


@pytest.mark.asyncio
async def test_kernel_executes_safe_chat(tmp_path):
    events = JsonlEventStore(tmp_path / "events.jsonl")
    kernel = HydraKernel(events=events)
    task = HydraTask(goal="Hola HYDRA")
    result = await kernel.run(task, FakeLLM())
    assert result.status == TaskStatus.COMPLETED
    assert result.answer == "HYDRA local test response"
    assert result.metadata["model_id"] == "local-main"
    names = [e.event_type for e in events.for_aggregate(task.id)]
    assert "hydra.plan.created" in names
    assert "hydra.task.completed" in names
