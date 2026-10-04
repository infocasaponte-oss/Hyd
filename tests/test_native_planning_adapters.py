# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib

import pytest

from hydra.core.native_contracts import HydraTask, TaskType
from hydra.router.router import CognitiveRouter
from hydra.scheduler.planner import Planner


@pytest.mark.parametrize("kind,capability,verify,tools", [
    (TaskType.CHAT, "chat.multilingual", False, False),
    (TaskType.TRANSLATION, "language.translate", False, False),
    (TaskType.CODING, "coding.general", True, True),
    (TaskType.RESEARCH, "research.general", True, True),
    (TaskType.REASONING, "reasoning.general", True, False),
    (TaskType.TOOL_USE, "tool.execute", True, True),
])
def test_platform_native_adapters_preserve_routes_and_dependencies(kind, capability, verify, tools):
    task = HydraTask(goal="explicit goal", task_type=kind)
    route = CognitiveRouter().route_native(task)
    assert route.model_dump() == dict(task_type=kind, capability=capability,
                                     needs_verification=verify, needs_tools=tools,
                                     parallelism=1, confidence=0.90)
    plan = Planner().create_native(task, route)
    assert plan.task_id == task.id
    assert plan.steps[0].instruction == task.goal
    assert plan.steps[0].capability == capability
    if kind in {TaskType.CODING, TaskType.RESEARCH, TaskType.TOOL_USE}:
        assert len(plan.steps) == 1
        assert plan.steps[0].kind.value == "tool"
        assert plan.steps[0].side_effects is True
    elif kind == TaskType.REASONING:
        assert [step.kind.value for step in plan.steps] == ["model", "verify"]
        assert plan.steps[1].depends_on == [plan.steps[0].id]
        assert plan.steps[1].capability == "verify.text"
    else:
        assert len(plan.steps) == 1
        assert plan.steps[0].kind.value == "model"
        assert plan.steps[0].side_effects is False


@pytest.mark.parametrize("old,new", [
    ("hydra.runtime.contracts", "hydra.core.native_contracts"),
    ("hydra.runtime.router", "hydra.router.native"),
    ("hydra.runtime.planner", "hydra.scheduler.native"),
])
def test_legacy_module_aliases_share_classes(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)
