# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.contracts import HydraTask
from hydra.runtime.planner import Planner, StepKind
from hydra.runtime.router import CapabilityRouter


def test_chat_plan_is_model_only():
    task = HydraTask(goal="Hola")
    route = CapabilityRouter().route(task)
    plan = Planner().build(task, route)
    assert [step.kind for step in plan.steps] == [StepKind.MODEL]


def test_coding_plan_is_side_effecting_until_sandbox():
    task = HydraTask(goal="Debug this Python test")
    route = CapabilityRouter().route(task)
    plan = Planner().build(task, route)
    assert plan.steps[0].kind == StepKind.TOOL
    assert plan.steps[0].side_effects is True
