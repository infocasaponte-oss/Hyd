# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Simulation Engine for plans: state + action -> predicted outcomes, before acting.

    rule simulator · historical statistics · learned predictor · LLM prediction · sandbox

Reality hierarchy (how much each source is trusted):
    0 LLM prediction · 1 historical · 2 formal/static · 3 sandbox · 4 real experiment · 5 production

Predictions are compared with reality after execution; the Calibration Engine keeps a
per-simulator/domain bias that the planner compensates. Monte Carlo rollouts give
expected success, variance and tail risk; branch-and-bound prunes hopeless plans."""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.governance.security import RiskEngine
from hydra.planning.goals import ExecutionPlan, PlanNode, PlanWeights, plan_utility

REALITY_LEVEL = {"llm": 0, "historical": 1, "rules": 2, "static": 2, "sandbox": 3, "experiment": 4,
                 "production": 5}

log = logging.getLogger("hydra.planning")


class PredictedOutcome(BaseModel):
    probability: float
    world_delta: dict[str, Any] = Field(default_factory=dict)
    utility: float = 0.0
    risks: list[str] = Field(default_factory=list)


class SimulationResult(BaseModel):
    action_id: str
    source: str
    reality_level: int
    success_probability: float
    expected_cost: float = 0.0
    expected_duration_ms: float = 0.0
    expected_information_gain: float = 0.0
    possible_outcomes: list[PredictedOutcome] = Field(default_factory=list)


class ActionStats(BaseModel):
    n: int = 0
    successes: int = 0
    total_ms: float = 0.0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        return (self.successes + 1) / (self.n + 2)  # Laplace smoothing

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.n if self.n else 0.0


class HistoricalSimulator:
    """Per (goal_type, action) statistics learned from executions, in the ``planning/historical.json``
    document (``hydra.core.docstore``): every node adds its executions to the shared counts."""

    def __init__(self, path: Path | None = None, docs=None) -> None:
        from hydra.core.docstore import DocumentStore, KeyedModels

        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("planning/historical.json", path),
                                     ActionStats)

    @property
    def stats(self) -> dict[str, ActionStats]:
        return self._registry.all()

    def key(self, goal_type: str, action: str) -> str:
        return f"{goal_type}|{action.split(':')[0]}"

    def record(self, goal_type: str, action: str, success: bool, ms: float, cost: float = 0.0) -> None:
        def add(s: ActionStats | None) -> ActionStats:
            s = s or ActionStats()
            s.n += 1
            s.successes += int(success)
            s.total_ms += ms
            s.total_cost += cost
            return s

        self._registry.change(self.key(goal_type, action), add)

    def predict(self, goal_type: str, node: PlanNode) -> SimulationResult | None:
        s = self.stats.get(self.key(goal_type, node.action))
        if not s or s.n < 3:
            return None
        return SimulationResult(action_id=node.id, source="historical", reality_level=1,
                                success_probability=s.success_rate, expected_duration_ms=s.mean_ms or
                                node.estimated_duration_ms, expected_cost=s.total_cost / s.n)


class RuleSimulator:
    """Deterministic priors: reads are safe, writes are riskier, verification is cheap."""

    PRIORS = {"workspace.inspect": 0.99, "world.query": 0.97, "memory.search": 0.97, "verify": 0.99,
              "tests.run": 0.95, "model.reason": 0.85, "code.patch": 0.7}

    def predict(self, node: PlanNode) -> SimulationResult:
        p = self.PRIORS.get(node.action.split(":")[0], node.success_probability)
        return SimulationResult(action_id=node.id, source="rules", reality_level=2, success_probability=p,
                                expected_duration_ms=node.estimated_duration_ms, expected_cost=node.estimated_cost)


class CalibrationRecord(BaseModel):
    predicted: float
    actual: bool


class CalibrationEngine:
    """predicted .80 vs actual 62% -> over-confident: bias = mean(actual - predicted). Records live in the
    ``planning/calibration.json`` document; every node appends to the shared history (last 500 per key)."""

    def __init__(self, path: Path | None = None, docs=None) -> None:
        from hydra.core.docstore import DocumentStore, KeyedModels

        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("planning/calibration.json", path))
        self._raw = None
        self._data: dict[str, list[CalibrationRecord]] = {}

    @property
    def data(self) -> dict[str, list[CalibrationRecord]]:
        raw = self._registry.all()
        if raw is not self._raw:
            self._data = {k: [CalibrationRecord(**x) for x in v] for k, v in raw.items()}
            self._raw = raw
        return self._data

    def record(self, simulator: str, domain: str, predicted: float, actual: bool) -> None:
        rec = CalibrationRecord(predicted=predicted, actual=actual).model_dump()
        self._registry.change(f"{simulator}|{domain}", lambda cur: [*(cur or []), rec][-500:])

    def bias(self, simulator: str, domain: str) -> float:
        recs = self.data.get(f"{simulator}|{domain}", [])[-200:]
        if len(recs) < 5:
            return 0.0
        return sum(float(r.actual) - r.predicted for r in recs) / len(recs)

    def calibration_error(self, simulator: str, domain: str, bins: int = 5) -> float:
        """Expected calibration error."""
        recs = self.data.get(f"{simulator}|{domain}", [])
        if not recs:
            return 0.0
        err = 0.0
        for b in range(bins):
            lo, hi = b / bins, (b + 1) / bins
            sel = [r for r in recs if lo <= r.predicted < hi or (b == bins - 1 and r.predicted == 1.0)]
            if sel:
                err += len(sel) / len(recs) * abs(sum(r.actual for r in sel) / len(sel)
                                                  - sum(r.predicted for r in sel) / len(sel))
        return round(err, 4)

    def adjust(self, simulator: str, domain: str, p: float) -> float:
        return max(0.01, min(0.99, p + self.bias(simulator, domain)))


class SimulatorEnsemble:
    """Weighted by domain and by reality level; calibrated; with a risk estimate per node."""

    DOMAIN_WEIGHTS = {"coding": {"sandbox": 0.6, "static": 0.25, "rules": 0.1, "historical": 0.3, "llm": 0.15},
                      "default": {"historical": 0.45, "rules": 0.3, "llm": 0.25, "sandbox": 0.6}}

    def __init__(self, historical: HistoricalSimulator | None = None, calibration: CalibrationEngine | None = None,
                 risk: RiskEngine | None = None, sandbox_predict=None, llm_predict=None) -> None:
        self.historical = historical or HistoricalSimulator()
        self.rules = RuleSimulator()
        self.calibration = calibration or CalibrationEngine()
        self.risk = risk or RiskEngine()
        self.sandbox_predict = sandbox_predict  # callable(node) -> SimulationResult | None
        self.llm_predict = llm_predict

    def simulate_node(self, goal_type: str, node: PlanNode) -> SimulationResult:
        domain = "coding" if goal_type in ("debug", "memory_leak", "performance") else "default"
        weights = self.DOMAIN_WEIGHTS[domain]
        results = [self.rules.predict(node)]
        if (h := self.historical.predict(goal_type, node)) is not None:
            results.append(h)
        for fn in (self.sandbox_predict, self.llm_predict):
            if fn is not None:
                try:
                    if (r := fn(node)) is not None:
                        results.append(r)
                except Exception:  # an optional simulator never blocks planning
                    log.warning("simulator %s failed for %s", getattr(fn, "__name__", fn), node.action,
                                exc_info=True)
        wsum = p = dur = cost = 0.0
        for r in results:
            w = weights.get(r.source, 0.2) * (1 + r.reality_level / 5)
            adj = self.calibration.adjust(r.source, goal_type, r.success_probability)
            p += w * adj
            dur += w * r.expected_duration_ms
            cost += w * r.expected_cost
            wsum += w
        best_level = max(r.reality_level for r in results)
        return SimulationResult(action_id=node.id, source="ensemble", reality_level=best_level,
                                success_probability=round(p / wsum, 4), expected_duration_ms=round(dur / wsum, 1),
                                expected_cost=round(cost / wsum, 6))

    def evaluate(self, goal_type: str, plan: ExecutionPlan, weights: PlanWeights, *, rollouts: int = 200,
                 budget_cost: float = 1.0, budget_ms: float = 120_000, info_gain: float = 0.0,
                 seed: int = 0) -> ExecutionPlan:
        for n in plan.nodes:
            if n.status != "pending":
                continue
            sim = self.simulate_node(goal_type, n)
            n.success_probability = sim.success_probability
            n.estimated_duration_ms = sim.expected_duration_ms
            n.estimated_cost = sim.expected_cost
            cap = n.action.replace("tool:", "").split(":")[0]
            n.risk = self.risk.score(self.risk.profile(cap), sandboxed=cap in ("python.execute", "tests.run"))
            n.reversible = self.risk.profile(cap).reversible
        plan.recompute()
        plan.information_gain = info_gain
        succ, costs = monte_carlo(plan, rollouts, seed)
        plan.expected_success = round(sum(succ) / len(succ), 4)
        mean = plan.expected_success
        plan.variance = round(sum((s - mean) ** 2 for s in succ) / len(succ), 4)
        plan.tail_risk = round(sum(1 for c in costs if c > budget_ms) / len(costs), 4)
        plan.utility = plan_utility(plan, weights, budget_cost, budget_ms) - 0.3 * plan.tail_risk
        return plan


def monte_carlo(plan: ExecutionPlan, n: int, seed: int = 0, retries: int = 1) -> tuple[list[float], list[float]]:
    """Each rollout samples node outcomes (one retry per node); returns success flags and durations."""
    rng = random.Random(seed)
    pending = [x for x in plan.nodes if x.status == "pending"]
    succ, durs = [], []
    for _ in range(max(1, n)):
        ok, total = 1.0, 0.0
        for node in pending:
            attempts = 0
            while True:
                attempts += 1
                total += node.estimated_duration_ms * rng.uniform(0.6, 1.8)
                if rng.random() < node.success_probability:
                    break
                if attempts > retries:
                    ok = 0.0
                    break
            if not ok:
                break
        succ.append(ok)
        durs.append(total)
    return succ, durs


def branch_and_bound(plans: list[ExecutionPlan], evaluate) -> list[ExecutionPlan]:
    """Cheap upper bound (plan.expected_success from priors) first; skip plans that cannot win."""
    ranked = sorted(plans, key=lambda p: -p.expected_success)
    best: ExecutionPlan | None = None
    evaluated = []
    for p in ranked:
        upper = p.expected_success * 1.0 + p.information_gain  # utility cannot exceed success + info
        if best is not None and upper < best.utility:
            p.utility = -math.inf
            continue
        evaluate(p)
        evaluated.append(p)
        if best is None or p.utility > best.utility:
            best = p
    return evaluated
