# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Goals with objective success/failure conditions and executable plan DAGs.

A plan is not text: it is an object with dependencies, preconditions, expected effects,
cost, duration, risk and reversibility, so HYDRA knows objectively when to stop instead
of asking a model whether it "thinks" it is done."""

from __future__ import annotations

import math
import operator
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq,
       "!=": operator.ne, "contains": lambda a, b: b in (a or ""), "in": lambda a, b: a in b}


class Condition(BaseModel):
    metric: str
    operator: str = "=="
    value: Any = True
    tolerance: float | None = None

    def holds(self, metrics: dict[str, Any]) -> bool | None:
        """True/False, or None when the metric has not been observed yet."""
        if self.metric not in metrics:
            return None
        actual = metrics[self.metric]
        if self.tolerance is not None and isinstance(actual, (int, float)) and isinstance(self.value, (int, float)):
            if self.operator == "==":
                return abs(actual - self.value) <= self.tolerance
        try:
            return bool(OPS[self.operator](actual, self.value))
        except (TypeError, KeyError):
            return False

    def __str__(self) -> str:
        return f"{self.metric} {self.operator} {self.value!r}"


class Goal(BaseModel):
    id: str = Field(default_factory=lambda: f"goal-{uuid4().hex[:10]}")
    description: str
    goal_type: str = "generic"
    success_conditions: list[Condition] = Field(default_factory=list)
    failure_conditions: list[Condition] = Field(default_factory=list)
    priority: float = 0.5
    deadline: datetime | None = None
    parent_goal_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    def status(self, metrics: dict[str, Any]) -> str:
        """achieved | failed | open"""
        if any(c.holds(metrics) is True for c in self.failure_conditions):
            return "failed"
        if self.success_conditions and all(c.holds(metrics) is True for c in self.success_conditions):
            return "achieved"
        return "open"

    def progress(self, metrics: dict[str, Any]) -> float:
        if not self.success_conditions:
            return 0.0
        return sum(1 for c in self.success_conditions if c.holds(metrics)) / len(self.success_conditions)


class PlanNode(BaseModel):
    id: str
    action: str
    """model.reason | tool:<name> | tests.run | code.patch | workspace.inspect | world.query | memory.search |
    experiment:<hypothesis> | verify | subgoal"""
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    preconditions: list[Condition] = Field(default_factory=list)
    expected_effects: list[dict[str, Any]] = Field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_duration_ms: float = 1000.0
    success_probability: float = 0.9
    reversible: bool = True
    risk: float = 0.0
    milestone: str | None = None
    status: str = "pending"  # pending | running | done | failed | skipped | blocked
    result: dict[str, Any] | None = None


class ExecutionPlan(BaseModel):
    id: str = Field(default_factory=lambda: f"plan-{uuid4().hex[:10]}")
    goal_id: str
    source: str = "htn"
    """htn | procedure:<id> | llm | value_model | replan"""
    nodes: list[PlanNode]
    version: int = 1
    estimated_cost: float = 0.0
    estimated_duration_ms: float = 0.0
    expected_success: float = 0.0
    risk_score: float = 0.0
    information_gain: float = 0.0
    utility: float = 0.0
    variance: float = 0.0
    tail_risk: float = 0.0

    def node(self, node_id: str) -> PlanNode:
        return next(n for n in self.nodes if n.id == node_id)

    def validate_dag(self) -> list[str]:
        ids = {n.id for n in self.nodes}
        errors = [f"{n.id} depends on unknown {d}" for n in self.nodes for d in n.dependencies if d not in ids]
        order = self.topological()
        if len(order) != len(self.nodes):
            errors.append("cycle detected")
        return errors

    def topological(self) -> list[str]:
        indeg = {n.id: len(n.dependencies) for n in self.nodes}
        children: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for n in self.nodes:
            for d in n.dependencies:
                if d in children:
                    children[d].append(n.id)
        ready = [i for i, d in indeg.items() if d == 0]
        out = []
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for c in children[cur]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    ready.append(c)
        return out

    def ready(self) -> list[PlanNode]:
        done = {n.id for n in self.nodes if n.status in ("done", "skipped")}
        return [n for n in self.nodes if n.status == "pending" and all(d in done for d in n.dependencies)]

    def critical_path_ms(self) -> float:
        finish: dict[str, float] = {}
        for nid in self.topological():
            n = self.node(nid)
            finish[nid] = n.estimated_duration_ms + max((finish[d] for d in n.dependencies if d in finish), default=0)
        return max(finish.values(), default=0.0)

    def recompute(self) -> ExecutionPlan:
        self.estimated_cost = round(sum(n.estimated_cost for n in self.nodes), 6)
        self.estimated_duration_ms = round(self.critical_path_ms(), 1)
        self.expected_success = round(math.prod(n.success_probability for n in self.nodes), 4) if self.nodes else 0
        self.risk_score = round(max((n.risk for n in self.nodes), default=0.0), 4)
        return self


class PlanWeights(BaseModel):
    success: float = 1.0
    cost: float = 0.2
    latency: float = 0.2
    risk: float = 0.5
    information: float = 0.3

    @classmethod
    def for_mode(cls, mode: str) -> PlanWeights:
        return {"fast": cls(latency=0.6, success=0.8), "deep": cls(success=1.4, latency=0.05, information=0.5),
                "max": cls(success=1.6, latency=0.02, cost=0.05), "private": cls(risk=0.8),
                "eco": cls(cost=0.6, latency=0.1)}.get(mode, cls())


def plan_utility(plan: ExecutionPlan, w: PlanWeights, budget_cost: float = 1.0, budget_ms: float = 120_000) -> float:
    """U(P) = w_s·S - w_c·C - w_l·L - w_r·R + w_i·I"""
    return round(w.success * plan.expected_success
                 - w.cost * min(1.0, plan.estimated_cost / max(1e-9, budget_cost))
                 - w.latency * min(1.0, plan.estimated_duration_ms / max(1.0, budget_ms))
                 - w.risk * plan.risk_score + w.information * plan.information_gain, 4)


def pareto_plans(plans: list[ExecutionPlan]) -> list[ExecutionPlan]:
    """Keep plans that are not dominated on (success, -cost, -latency, -risk)."""
    def dom(a: ExecutionPlan, b: ExecutionPlan) -> bool:
        ka = (a.expected_success, -a.estimated_cost, -a.estimated_duration_ms, -a.risk_score)
        kb = (b.expected_success, -b.estimated_cost, -b.estimated_duration_ms, -b.risk_score)
        return all(x >= y for x, y in zip(ka, kb)) and ka != kb
    return [p for p in plans if not any(dom(q, p) for q in plans if q is not p)]
