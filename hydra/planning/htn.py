# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Goal decomposition (Hierarchical Task Network templates) and goal inference.

    GOAL Reduce memory leak
    ├── Diagnose  (inspect metrics, inspect allocations, formulate hypotheses)
    ├── Validate  (design experiments, rank hypotheses)
    ├── Repair    (create patch, run tests)
    └── Verify    (benchmark, regression tests)

Only the next milestone is expanded in detail (long-horizon, receding-horizon planning)."""

from __future__ import annotations

import re

from hydra.planning.goals import Condition, ExecutionPlan, Goal, PlanNode

KEYWORDS = [
    ("debug", re.compile(r"(?i)\b(bug|error|falla|fallo|traceback|excepci[oó]n|exception|corrige|fix|arregla|"
                         r"debug|depura)\b")),
    ("memory_leak", re.compile(r"(?i)\b(memory leak|fuga de memoria|consumo de memoria|memory growth)\b")),
    ("performance", re.compile(r"(?i)\b(lent[oa]|slow|latencia|latency|rendimiento|performance|optimiza)\b")),
    ("research", re.compile(r"(?i)\b(investiga|research|compara|compare|estado del arte|analiza a fondo)\b")),
    ("translate", re.compile(r"(?i)\b(traduce|translate|traducción)\b")),
]


def infer_goal(description: str, context: dict | None = None) -> Goal:
    gtype = next((name for name, rx in KEYWORDS if rx.search(description)), "generic")
    ctx = dict(context or {})
    success: list[Condition]
    if gtype in ("debug", "memory_leak"):
        success = [Condition(metric="tests_pass", operator="==", value=True)]
        if gtype == "memory_leak":
            success.append(Condition(metric="memory_growth_mb_hour", operator="<", value=20))
    elif gtype == "performance":
        success = [Condition(metric="tests_pass", operator="==", value=True),
                   Condition(metric="latency_improvement_pct", operator=">=", value=ctx.get("target_pct", 10))]
    else:
        success = [Condition(metric="answer_confidence", operator=">=", value=ctx.get("min_confidence", 0.8))]
    failure = [Condition(metric="budget_exhausted", operator="==", value=True),
               Condition(metric="policy_blocked", operator="==", value=True)]
    return Goal(description=description, goal_type=gtype, success_conditions=success, failure_conditions=failure,
                context=ctx)


def _n(i: int, action: str, deps: list[int], milestone: str, p: float = 0.9, ms: float = 2000, cost: float = 0.0,
       reversible: bool = True, **args) -> PlanNode:
    return PlanNode(id=f"S{i}", action=action, dependencies=[f"S{d}" for d in deps], milestone=milestone,
                    success_probability=p, estimated_duration_ms=ms, estimated_cost=cost, reversible=reversible,
                    arguments=args)


def decompose(goal: Goal) -> list[ExecutionPlan]:
    """Candidate plans for a goal (alternative strategies, not only one template)."""
    d = goal.description
    has_ws = bool(goal.context.get("workspace"))
    plans: list[ExecutionPlan] = []
    if goal.goal_type in ("debug", "memory_leak", "performance") and has_ws:
        # A: observe first (reversible-first), targeted tests, patch, verify
        plans.append(ExecutionPlan(goal_id=goal.id, source="htn:observe-first", nodes=[
            _n(1, "workspace.inspect", [], "diagnose", 0.99, 200),
            _n(2, "tests.run", [1], "diagnose", 0.95, 8000),
            _n(3, "model.reason", [1, 2], "diagnose", 0.85, 15000, 0.002,
               prompt=f"Diagnose the root cause. Goal: {d}"),
            _n(4, "code.patch", [3], "repair", 0.75, 20000, 0.004, reversible=True, prompt=d),
            _n(5, "tests.run", [4], "verify", 0.9, 8000),
            _n(6, "verify", [5], "verify", 0.99, 50),
        ]))
        # B: patch directly (cheaper, riskier)
        plans.append(ExecutionPlan(goal_id=goal.id, source="htn:patch-first", nodes=[
            _n(1, "workspace.inspect", [], "diagnose", 0.99, 200),
            _n(2, "code.patch", [1], "repair", 0.6, 20000, 0.004, prompt=d),
            _n(3, "tests.run", [2], "verify", 0.9, 8000),
            _n(4, "verify", [3], "verify", 0.99, 50),
        ]))
    elif goal.goal_type == "research":
        plans.append(ExecutionPlan(goal_id=goal.id, source="htn:research", nodes=[
            _n(1, "world.query", [], "gather", 0.95, 100, query=d),
            _n(2, "memory.search", [], "gather", 0.95, 200, query=d),
            _n(3, "model.reason", [1, 2], "synthesize", 0.85, 30000, 0.004, prompt=d, mode="deep"),
            _n(4, "verify", [3], "verify", 0.99, 50),
        ]))
    else:
        plans.append(ExecutionPlan(goal_id=goal.id, source="htn:direct", nodes=[
            _n(1, "model.reason", [], "answer", 0.85, 8000, 0.001, prompt=d),
            _n(2, "verify", [1], "verify", 0.99, 50),
        ]))
        plans.append(ExecutionPlan(goal_id=goal.id, source="htn:context-first", nodes=[
            _n(1, "world.query", [], "gather", 0.95, 100, query=d),
            _n(2, "memory.search", [], "gather", 0.95, 200, query=d),
            _n(3, "model.reason", [1, 2], "answer", 0.88, 9000, 0.001, prompt=d),
            _n(4, "verify", [3], "verify", 0.99, 50),
        ]))
    for p in plans:
        p.recompute()
    return plans
