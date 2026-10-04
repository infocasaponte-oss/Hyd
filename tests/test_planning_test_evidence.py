# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock

from hydra.planning.goals import Goal, PlanNode
from hydra.planning.runner import GoalRunner
from hydra.tools.workspace import TestRunResult as RunResult


async def test_targeted_success_does_not_replace_failed_full_suite(runtime, tmp_path, monkeypatch):
    run = AsyncMock(side_effect=[RunResult(success=False, failed=1), RunResult(success=True, passed=1)])
    monkeypatch.setattr("hydra.tools.workspace.run_tests", run)
    runner = GoalRunner(runtime)
    goal = Goal(description="Fix bug", context={"workspace": str(tmp_path)})
    state = {"context": [], "metrics": {}}
    for node in [PlanNode(id="full", action="tests.run"),
                 PlanNode(id="target", action="tests.run", arguments={"pattern": "test_target.py"})]:
        _, metrics, _ = await runner._act(node, goal, state, "balanced")
        state["metrics"].update(metrics)
    assert state["metrics"]["targeted_tests_pass"] is True
    assert state["metrics"]["tests_pass"] is False
    assert state["full_suite_tests_pass"] is False
    assert state["baseline_tests_pass"] is False


async def test_patch_invalidates_previous_test_success(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.kernel, "run", AsyncMock(return_value=SimpleNamespace(
        answer="### FILE: solve.py\n```python\ndef solve():\n    return 42\n```")))
    runner = GoalRunner(runtime)
    state = {"context": [], "metrics": {"tests_pass": True}, "full_suite_tests_pass": True}
    goal = Goal(description="Fix bug", context={"workspace": str(tmp_path)})
    await runner._act(PlanNode(id="patch", action="code.patch"), goal, state, "balanced")
    assert state["metrics"]["tests_pass"] is False
    assert state["full_suite_tests_pass"] is False
    assert state["workspace_patched"] is True
