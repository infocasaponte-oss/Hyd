# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.tool_audit import AuditedToolRuntime
from hydra.runtime.tool_runtime import ToolRuntime
from hydra.runtime.tools import Workspace


@pytest.mark.asyncio
async def test_tool_call_emits_audit_events(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "a.txt").write_text("A")
    events = JsonlEventStore(tmp_path / "events.jsonl")
    runtime = AuditedToolRuntime(ToolRuntime(Workspace(workspace)), events)
    task_id = uuid4()
    await runtime.run(
        task_id=task_id,
        trace_id="trace",
        name="workspace.read",
        arguments={"path": "a.txt"},
    )
    names = [event.event_type for event in events.for_aggregate(task_id)]
    assert names == ["hydra.tool.requested", "hydra.tool.completed"]
