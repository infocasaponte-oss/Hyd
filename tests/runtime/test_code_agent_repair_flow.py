# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
from uuid import uuid4

import pytest

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.code_agent import CodeAgent
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.sandbox import SandboxResult
from hydra.runtime.workspaces import WorkspaceManager


class RepairLLM:
    def __init__(self):
        self.prompt = ""

    async def chat(self, messages, *, temperature=0.0, max_tokens=1024):
        self.prompt = messages[0]["content"]
        return (
            "```diff\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
            "```"
        )


class RepairSandbox:
    image = "hydra-sandbox:py311-v1"

    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = 0

    async def preflight(self):
        return SandboxResult(True, "ok", 0)

    async def pytest(self, target="."):
        self.calls += 1
        if self.calls == 1:
            return SandboxResult(False, "FAILED app.py:1 - expected 2", 1)
        return SandboxResult(True, f"1 passed for {target}", 0)

    async def py_compile(self, paths):
        assert paths == ["app.py"]
        return SandboxResult(True, "syntax ok", 0)

    async def ruff_check(self, paths):
        assert paths == ["app.py"]
        return SandboxResult(True, "ruff ok", 0)

    async def mypy_check(self, paths):
        assert paths == ["app.py"]
        return SandboxResult(True, "mypy ok", 0)


@pytest.mark.asyncio
async def test_code_agent_demonstrates_repair_and_uses_source_context(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n")
    init = await asyncio.create_subprocess_exec(
        "git", "init",
        cwd=source,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await init.communicate()
    assert init.returncode == 0
    add = await asyncio.create_subprocess_exec(
        "git", "add", "app.py",
        cwd=source,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await add.communicate()
    assert add.returncode == 0

    llm = RepairLLM()
    agent = CodeAgent(
        llm,
        WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path),
        ArtifactStore(tmp_path / "artifacts"),
        JsonlEventStore(tmp_path / "events.jsonl"),
        sandbox_factory=RepairSandbox,
    )

    result = await agent.run(
        task_id=uuid4(),
        trace_id="trace",
        goal="Make VALUE equal 2",
        source=source,
        max_tokens=256,
    )

    assert result.accepted is True
    assert "FILE: app.py" in llm.prompt
    assert "VALUE = 1" in llm.prompt
    assert (result.workspace.root / "app.py").read_text() == "VALUE = 2\n"
    kinds = [record.kind for record in result.artifacts]
    assert "applied-patch" in kinds
    assert "verified-patch" in kinds
    assert "verification-report" in kinds
    assert "syntax-check" in kinds
    assert "tests-targeted" in kinds
    assert "ruff-check" in kinds
    assert "mypy-check" in kinds
