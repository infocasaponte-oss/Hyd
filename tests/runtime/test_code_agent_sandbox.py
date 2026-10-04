# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.code_agent import CodeAgent
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.sandbox import SandboxResult
from hydra.runtime.workspaces import WorkspaceManager


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls += 1
        return "should not be called"


class UnavailableSandbox:
    image = "hydra-sandbox:py311-v1"

    def __init__(self, workspace):
        self.workspace = workspace

    async def preflight(self):
        return SandboxResult(False, "missing image", 125)

    async def pytest(self, target="."):
        raise AssertionError("pytest must not run after failed preflight")


@pytest.mark.asyncio
async def test_code_agent_aborts_before_llm_when_sandbox_unavailable(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "test_sample.py").write_text("def test_ok(): assert True")

    llm = FakeLLM()
    events = JsonlEventStore(tmp_path / "events.jsonl")
    agent = CodeAgent(
        llm,
        WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path),
        ArtifactStore(tmp_path / "artifacts"),
        events,
        sandbox_factory=UnavailableSandbox,
    )

    result = await agent.run(
        task_id=uuid4(),
        trace_id="trace",
        goal="fix it",
        source=source,
        max_tokens=128,
    )

    assert result.accepted is False
    assert llm.calls == 0
    assert "Sandbox unavailable" in result.answer
    assert "hydra.code.sandbox_unavailable" in (tmp_path / "events.jsonl").read_text()


class PassingSandbox:
    image = "hydra-sandbox:py311-v1"

    def __init__(self, workspace):
        self.workspace = workspace

    async def preflight(self):
        return SandboxResult(True, "ok", 0)

    async def pytest(self, target="."):
        return SandboxResult(True, "1 passed", 0)


@pytest.mark.asyncio
async def test_code_agent_requires_failing_baseline_before_llm(tmp_path):
    source = tmp_path / "repo-passing"
    source.mkdir()
    (source / "test_sample.py").write_text("def test_ok(): assert True")

    llm = FakeLLM()
    events = JsonlEventStore(tmp_path / "events-passing.jsonl")
    agent = CodeAgent(
        llm,
        WorkspaceManager(tmp_path / "workspaces-passing", source_root=tmp_path),
        ArtifactStore(tmp_path / "artifacts-passing"),
        events,
        sandbox_factory=PassingSandbox,
    )

    result = await agent.run(
        task_id=uuid4(),
        trace_id="trace",
        goal="fix it",
        source=source,
        max_tokens=128,
    )

    assert result.accepted is False
    assert llm.calls == 0
    assert "Baseline tests already pass" in result.answer
    assert "hydra.code.baseline_passing" in (
        tmp_path / "events-passing.jsonl"
    ).read_text()
