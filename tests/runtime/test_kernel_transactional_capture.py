# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.capture_uow import CaptureUnitOfWork
from hydra.runtime.contracts import HydraTask, TaskStatus
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.kernel import HydraKernel
from hydra.runtime.outbox_dispatcher import OutboxDispatcher
from hydra.runtime.provenance import ProvenanceLedger


class FakeLLM:
    async def chat(self, messages, *, temperature=0.2, max_tokens=1024):
        return "transactional answer"


@pytest.mark.asyncio
async def test_kernel_commits_terminal_state_before_marking_completed(tmp_path):
    database = tmp_path / "hydra.db"
    events = JsonlEventStore(tmp_path / "events.jsonl")
    provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")
    uow = CaptureUnitOfWork(database)
    kernel = HydraKernel(events=events, capture_uow=uow)
    task = HydraTask(goal="Hola")

    result = await kernel.run(task, FakeLLM())

    assert result.status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    committed = uow.get_task_commit(task.id)
    assert committed is not None
    assert committed.status == "completed"

    pending = uow.outbox.pending()
    assert {message.topic for message in pending} == {"event", "provenance"}

    dispatch = OutboxDispatcher(uow.outbox, events, provenance).dispatch_once()
    assert dispatch.published == 2
    names = [event.event_type for event in events.for_aggregate(task.id)]
    assert "hydra.task.completed" in names
    assert events.verify_integrity().valid is True
    assert provenance.verify_integrity().valid is True


class FailingCapture:
    def commit_terminal(self, *args, **kwargs):
        raise RuntimeError("storage unavailable")


@pytest.mark.asyncio
async def test_failed_terminal_commit_does_not_mark_task_completed(tmp_path):
    kernel = HydraKernel(
        events=JsonlEventStore(tmp_path / "events.jsonl"),
        capture_uow=FailingCapture(),
    )
    task = HydraTask(goal="Hola")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await kernel.run(task, FakeLLM())

    assert task.status == TaskStatus.SYNTHESIZING
