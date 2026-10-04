# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import pytest

from hydra.core.durable_events import JsonlEventStore
from hydra.core.native_contracts import CognitiveBudget, HydraTask, TaskStatus
from hydra.core.native_kernel import HydraKernel
from hydra.core.task_commit import CaptureUnitOfWork


class BlockedInference:
    def __init__(self):
        self.cancelled = False

    async def chat(self, *args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True

    async def execute(self, **kwargs):
        return await self.chat()


@pytest.mark.asyncio
@pytest.mark.parametrize("physical", [False, True])
async def test_deadline_cancels_inference_without_terminal_commit(tmp_path, physical):
    blocked = BlockedInference()
    events = JsonlEventStore(tmp_path / "events.jsonl")
    capture = CaptureUnitOfWork(tmp_path / "hydra.db")
    kernel = HydraKernel(
        events=events, capture_uow=capture,
        runtime_bridge=blocked if physical else None,
    )
    task = HydraTask(goal="Hola", budget=CognitiveBudget(max_seconds=0.02))
    with pytest.raises(TimeoutError):
        await kernel.run(task, blocked)
    assert blocked.cancelled
    assert task.status == TaskStatus.FAILED
    assert capture.get_task_commit(task.id) is None
    assert capture.outbox.pending() == []
    names = [event.event_type for event in events.for_aggregate(task.id)]
    assert "hydra.task.failed" in names
    assert "hydra.task.completed" not in names
