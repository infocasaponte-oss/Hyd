# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Procedural memory (versioned procedures), the Procedure Miner and the Value Model.

    successful traces -> common successful subsequence -> PROCEDURE_CANDIDATE
    -> shadow -> canary -> ACTIVE   (never activated directly)

The value model learns Q(state, action) from executions (action-value corpus). When it is
confident (System 1) HYDRA acts immediately; otherwise it falls back to the full
planner/simulator (System 2). There is always a heuristic fallback."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.core.hashing import now_iso
from hydra.planning.goals import Condition, ExecutionPlan, PlanNode

STAGES = ["CANDIDATE", "SHADOW", "CANARY", "ACTIVE", "DEPRECATED", "RETIRED"]


class Procedure(BaseModel):
    id: str = Field(default_factory=lambda: f"PROC-{uuid4().hex[:6]}")
    name: str
    domain: str
    version: int = 1
    status: str = "CANDIDATE"
    trigger: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[Condition] = Field(default_factory=list)
    steps: list[str]
    success_conditions: list[Condition] = Field(default_factory=list)
    executions: int = 0
    successes: int = 0
    avg_cost: float = 0.0
    avg_duration_ms: float = 0.0
    derived_from_traces: int = 0
    created_at: str = Field(default_factory=now_iso)
    parent: str | None = None

    @property
    def success_rate(self) -> float:
        return self.successes / self.executions if self.executions else 0.0

    def to_plan(self, goal_id: str, arguments: dict[str, dict] | None = None) -> ExecutionPlan:
        nodes = [PlanNode(id=f"S{i + 1}", action=a, dependencies=[f"S{i}"] if i else [],
                          arguments=(arguments or {}).get(a, {}),
                          success_probability=max(0.5, self.success_rate) if self.executions else 0.85)
                 for i, a in enumerate(self.steps)]
        return ExecutionPlan(goal_id=goal_id, source=f"procedure:{self.id}@v{self.version}", nodes=nodes).recompute()


class Trace(BaseModel):
    goal_type: str
    actions: list[str]
    success: bool
    cost: float = 0.0
    duration_ms: float = 0.0


def lcs(a: list[str], b: list[str]) -> list[str]:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            out.append(a[i])
            i, j = i + 1, j + 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


class ProcedureMiner:
    def __init__(self, min_support: int = 3, min_success: float = 0.7, min_len: int = 2) -> None:
        self.min_support = min_support
        self.min_success = min_success
        self.min_len = min_len

    def mine(self, traces: list[Trace]) -> list[Procedure]:
        by_type: dict[str, list[Trace]] = defaultdict(list)
        for t in traces:
            by_type[t.goal_type].append(t)
        out = []
        for gtype, group in by_type.items():
            ok = [t for t in group if t.success and t.actions]
            if len(ok) < self.min_support:
                continue
            rate = len(ok) / len(group)
            if rate < self.min_success:
                continue
            # most frequent exact sequence, else LCS of successful traces
            common = Counter(tuple(t.actions) for t in ok).most_common(1)[0]
            seq = list(common[0]) if common[1] >= self.min_support else None
            if seq is None:
                seq = ok[0].actions
                for t in ok[1:]:
                    seq = lcs(seq, t.actions)
            if len(seq) < self.min_len:
                continue
            support = sum(1 for t in ok if lcs(seq, t.actions) == seq)
            if support < self.min_support:
                continue
            out.append(Procedure(name=f"{gtype}-procedure", domain=gtype, steps=seq, trigger={"goal_type": gtype},
                                 executions=support, successes=support, derived_from_traces=len(group),
                                 avg_cost=sum(t.cost for t in ok) / len(ok),
                                 avg_duration_ms=sum(t.duration_ms for t in ok) / len(ok)))
        return out


class ProcedureStore:
    """Learned procedures in the ``planning/procedures.json`` document (``hydra.core.docstore``). Every
    change is applied to the latest list with the document locked: versions, statistics and promotions
    made on other nodes are never overwritten."""

    def __init__(self, path: Path, docs=None) -> None:
        from hydra.core.docstore import DocumentStore

        self.path = path
        self._doc = (docs or DocumentStore()).document("planning/procedures.json", path, default=list)
        self._raw = None
        self._items: dict[str, Procedure] = {}

    @property
    def items(self) -> dict[str, Procedure]:
        raw = self._doc.get()
        if raw is not self._raw:
            self._items = {p["id"]: Procedure(**p) for p in raw}
            self._raw = raw
        return self._items

    def _change(self, fn: Callable[[dict[str, Procedure]], Procedure]) -> Procedure:
        holder = {}

        def apply(rows: list) -> list:
            items = {p["id"]: Procedure(**p) for p in rows}
            holder["p"] = fn(items)
            return [p.model_dump(mode="json") for p in items.values()]

        self._doc.update(apply)
        return holder["p"]

    def add(self, proc: Procedure) -> Procedure:
        def apply(items: dict[str, Procedure]) -> Procedure:
            same = [p for p in items.values() if p.domain == proc.domain and p.steps == proc.steps]
            if same:
                return same[0]
            prev = [p for p in items.values() if p.domain == proc.domain]
            if prev:
                proc.version = max(p.version for p in prev) + 1
                proc.parent = max(prev, key=lambda p: p.version).id
            items[proc.id] = proc
            return proc

        return self._change(apply)

    def record(self, proc_id: str, success: bool, cost: float, duration_ms: float) -> Procedure:
        def apply(items: dict[str, Procedure]) -> Procedure:
            p = items[proc_id]
            n = p.executions
            p.avg_cost = (p.avg_cost * n + cost) / (n + 1)
            p.avg_duration_ms = (p.avg_duration_ms * n + duration_ms) / (n + 1)
            p.executions += 1
            p.successes += int(success)
            return p

        return self._change(apply)

    def advance(self, proc_id: str, min_executions: int = 5, min_success: float = 0.8) -> Procedure:
        """CANDIDATE -> SHADOW -> CANARY -> ACTIVE only with evidence."""
        def apply(items: dict[str, Procedure]) -> Procedure:
            p = items[proc_id]
            i = STAGES.index(p.status)
            if p.status in ("ACTIVE", "DEPRECATED", "RETIRED"):
                return p
            if p.status != "CANDIDATE" and (p.executions < min_executions or p.success_rate < min_success):
                return p
            p.status = STAGES[i + 1]
            if p.status == "ACTIVE":
                for other in items.values():
                    if other.domain == p.domain and other.id != p.id and other.status == "ACTIVE":
                        other.status = "DEPRECATED"
            return p

        return self._change(apply)

    def best(self, domain: str, statuses: tuple[str, ...] = ("ACTIVE", "CANARY")) -> Procedure | None:
        cands = [p for p in self.items.values() if p.domain == domain and p.status in statuses]
        return max(cands, key=lambda p: (p.success_rate, -p.avg_duration_ms), default=None)

    def ab_compare(self, a: str, b: str) -> dict[str, Any]:
        pa, pb = self.items[a], self.items[b]
        winner = a if (pa.success_rate, -pa.avg_duration_ms) >= (pb.success_rate, -pb.avg_duration_ms) else b
        return {"a": {"id": a, "success": pa.success_rate, "ms": pa.avg_duration_ms, "n": pa.executions},
                "b": {"id": b, "success": pb.success_rate, "ms": pb.avg_duration_ms, "n": pb.executions},
                "winner": winner, "significant": min(pa.executions, pb.executions) >= 30}


class ValueModel:
    """Tabular action-value model Q(state_key, action) with visit counts (HYDRA-Value-1B's
    data source; a small trained model can replace it behind ``score``)."""

    def __init__(self, path: Path | None = None, docs=None) -> None:
        from hydra.core.docstore import DocumentStore, KeyedModels

        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("planning/value.json", path))

    @property
    def q(self) -> dict[str, dict[str, list[float]]]:
        """Q(state, action) as [total reward, visits]; every node adds its rewards to the shared totals."""
        return self._registry.all()

    @staticmethod
    def state_key(state: dict[str, Any]) -> str:
        return "|".join(f"{k}={state[k]}" for k in sorted(state) if isinstance(state[k], (str, int, bool)))

    def update(self, state: dict[str, Any], action: str, reward: float) -> None:
        def add(s: dict | None) -> dict:
            s = dict(s or {})
            total, n = s.get(action, [0.0, 0])
            s[action] = [total + reward, n + 1]
            return s

        self._registry.change(self.state_key(state), add)

    def score(self, state: dict[str, Any], actions: list[str]) -> dict[str, tuple[float, int]]:
        s = self.q.get(self.state_key(state), {})
        return {a: ((s[a][0] / s[a][1]), int(s[a][1])) if a in s else (0.5, 0) for a in actions}

    def choose(self, state: dict[str, Any], actions: list[str], min_visits: int = 5, margin: float = 0.15,
               explore: float = 0.0) -> tuple[str | None, float]:
        """System 1: return (action, confidence) when confident; (None, conf) -> use System 2."""
        sc = self.score(state, actions)
        total = sum(n for _, n in sc.values()) or 1
        ranked = sorted(actions, key=lambda a: -(sc[a][0] + explore * math.sqrt(math.log(total + 1) / (sc[a][1] + 1))))
        best = ranked[0]
        second = sc[ranked[1]][0] if len(ranked) > 1 else 0.0
        conf = sc[best][0] - second
        if sc[best][1] >= min_visits and conf >= margin:
            return best, round(conf, 3)
        return None, round(conf, 3)
