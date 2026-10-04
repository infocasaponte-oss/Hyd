# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import pytest

from hydra.core.budget import PRESETS
from hydra.core.contracts import ExecutionMode, HydraRequest, Message, RoutingDecision, TaskType
from hydra.core.state import InvalidTransition, TaskStateMachine, TaskStatus
from hydra.scheduler.graph import CycleError, ExecutionGraph
from hydra.scheduler.parallel import hedged, run_parallel, speculative
from hydra.scheduler.planner import NoModelAvailable, Planner

from .conftest import default_models


def route(c: float, **kw) -> RoutingDecision:
    return RoutingDecision(task_type=TaskType.REASONING, complexity=c, risk=kw.pop("risk", 0.1), **kw)


REQ = HydraRequest(messages=[Message(role="user", content="x")])


def test_planner_strategies():
    p, models = Planner(), default_models()
    b = PRESETS[ExecutionMode.BALANCED]
    assert p.create(route(0.2), models, b, REQ).strategy == "cascade"
    medium = p.create(route(0.6), models, b, REQ)
    assert medium.strategy == "specialist+critic"
    assert medium.steps[1].models[0] != medium.steps[0].models[0]  # independent critic
    hard = p.create(route(0.9, desired_parallelism=3), models, PRESETS[ExecutionMode.DEEP], REQ)
    assert hard.strategy == "ensemble+judge" and len(hard.steps[0].models) == 3
    fast = p.create(route(0.9), models, PRESETS[ExecutionMode.FAST], REQ)
    assert fast.strategy == "single"
    with pytest.raises(NoModelAvailable):
        p.create(route(0.2), [], b, REQ)


def test_cascade_starts_cheap():
    plan = Planner().create(route(0.2), default_models(), PRESETS[ExecutionMode.BALANCED], REQ)
    assert plan.steps[0].models == ["small"]


async def test_run_parallel_isolates_failures():
    async def ok():
        return 1

    async def bad():
        raise ValueError("x")

    res = await run_parallel([ok, bad, ok])
    assert res[0] == 1 and isinstance(res[1], ValueError) and res[2] == 1


async def test_hedged_backup_wins_when_primary_slow():
    cancelled = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "primary"

    async def fast():
        await asyncio.sleep(0.01)
        return "backup"

    result, who = await hedged(slow, fast, hedge_after_s=0.05)
    assert (result, who) == ("backup", "backup")
    assert cancelled.is_set()


async def test_speculative_cancels_losers():
    async def quick():
        await asyncio.sleep(0.01)
        return 0.97

    async def slow():
        await asyncio.sleep(5)
        return 0.5

    winner, finished = await asyncio.wait_for(speculative([slow, quick, slow], lambda r: r > 0.95), 2)
    assert winner == 0.97 and finished == [0.97]


async def test_graph_waves_and_cycle():
    g = ExecutionGraph()
    order = []

    def node(name):
        async def fn(inputs):
            order.append(name)
            return {name: sorted(inputs)}
        return fn

    for n in ("reasoner", "coder", "critic", "judge"):
        g.add_node(n, node(n))
    g.add_edge("reasoner", "critic")
    g.add_edge("coder", "judge")
    g.add_edge("critic", "judge")
    assert g.waves() == [["coder", "reasoner"], ["critic"], ["judge"]]
    out = await g.execute_parallel()
    assert out["judge"] == {"judge": ["coder", "critic"]}
    g.add_edge("judge", "reasoner")
    with pytest.raises(CycleError):
        g.waves()


def test_state_machine():
    sm = TaskStateMachine()
    for s in (TaskStatus.ROUTING, TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.VERIFYING,
              TaskStatus.SYNTHESIZING, TaskStatus.COMPLETED):
        sm.to(s)
    assert sm.terminal
    with pytest.raises(InvalidTransition):
        TaskStateMachine().to(TaskStatus.SYNTHESIZING)
    with pytest.raises(InvalidTransition):
        sm.to(TaskStatus.ROUTING)  # terminal states never move
