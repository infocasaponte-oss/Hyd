# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.coding_loop import CodingLoop
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.patching import PatchTool
from hydra.runtime.sandbox import SandboxResult
from hydra.runtime.tools import Workspace


class SequenceSandbox:
    def __init__(self, results):
        self.results = iter(results)

    async def pytest(self, target="."):
        return next(self.results)


@pytest.mark.asyncio
async def test_rejected_patch_restores_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".git" / "marker").write_text("preserve")
    (workspace / "a.txt").write_text("old\n")

    loop = CodingLoop(
        SequenceSandbox(
            [
                SandboxResult(True, "baseline passed", 0),
                SandboxResult(False, "verification failed", 1),
            ]
        ),
        PatchTool(Workspace(workspace)),
        ArtifactStore(tmp_path / "artifacts"),
        JsonlEventStore(tmp_path / "events.jsonl"),
    )
    diff = (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "--- /dev/null\n"
        "+++ b/created.txt\n"
        "@@ -0,0 +1 @@\n"
        "+temporary\n"
    )

    result = await loop.verify_patch(
        task_id=uuid4(),
        trace_id="trace-rollback",
        diff=diff,
    )

    assert not result.accepted
    assert (workspace / "a.txt").read_text() == "old\n"
    assert not (workspace / "created.txt").exists()
    assert (workspace / ".git" / "marker").read_text() == "preserve"


@pytest.mark.asyncio
async def test_accepted_patch_remains_in_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".git" / "marker").write_text("preserve")
    (workspace / "a.txt").write_text("old\n")

    loop = CodingLoop(
        SequenceSandbox(
            [
                SandboxResult(True, "baseline passed", 0),
                SandboxResult(True, "verification passed", 0),
            ]
        ),
        PatchTool(Workspace(workspace)),
        ArtifactStore(tmp_path / "artifacts"),
        JsonlEventStore(tmp_path / "events.jsonl"),
    )
    diff = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"

    result = await loop.verify_patch(
        task_id=uuid4(),
        trace_id="trace-accepted",
        diff=diff,
    )

    assert result.accepted
    assert (workspace / "a.txt").read_text() == "new\n"
