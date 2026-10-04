# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Learned router: (task, complexity, mode) -> which model actually works best, learned
from HYDRA's own telemetry, and A/B tested against the heuristic scorer.

    (task, context, hardware, budget) -> routing policy -> (model, depth, parallelism)
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from uuid import UUID

from pydantic import BaseModel

from hydra.core.contracts import HydraRequest, RoutingDecision
from hydra.registry.models import ModelProfile
from hydra.telemetry.metrics import InferenceRun

GENERATION_ROLES = {"reasoner", "coder"}


def complexity_bucket(c: float | None) -> str:
    if c is None:
        return "any"
    return "low" if c < 0.3 else "mid" if c < 0.6 else "high" if c < 0.8 else "max"


class ArmStats(BaseModel):
    arm: str
    tasks: int
    mean_confidence: float | None
    mean_quality: float | None
    mean_latency_ms: float | None


class LearnedRoutingPolicy:
    def __init__(self, min_samples: int = 20, latency_weight: float = 0.05, prior_strength: float = 5.0) -> None:
        self.min_samples = min_samples
        self.latency_weight = latency_weight
        self.prior_strength = prior_strength
        # (task_type, bucket, mode) -> model -> [n, sum_quality, sum_latency]
        self.table: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0.0, 0.0]))
        self.samples = 0

    def fit(self, runs: list[InferenceRun]) -> int:
        self.table.clear()
        self.samples = 0
        for r in runs:
            if r.role not in GENERATION_ROLES or r.quality is None:
                continue
            for key in ((r.task_type, complexity_bucket(r.complexity), r.mode or "any"),
                        (r.task_type, "any", "any")):
                cell = self.table[key][r.model_id]
                cell[0] += 1
                cell[1] += r.quality
                cell[2] += r.latency_ms
            self.samples += 1
        return self.samples

    def expected(self, model: ModelProfile, route: RoutingDecision, request: HydraRequest) -> tuple[float, int]:
        """Posterior quality (shrunk toward the model's prior) and the evidence count."""
        for key in ((route.task_type.value, complexity_bucket(route.complexity), request.mode.value),
                    (route.task_type.value, "any", "any")):
            cell = self.table.get(key, {}).get(model.id)
            if cell and cell[0] >= 3:
                n, sq, sl = cell
                prior = model.quality(route.task_type)
                quality = (sq + prior * self.prior_strength) / (n + self.prior_strength)
                utility = quality - self.latency_weight * math.log1p(sl / n / 1000)
                return utility, int(n)
        return model.quality(route.task_type) - 1.0, 0  # unknown: rank after known-good models

    def ready(self) -> bool:
        return self.samples >= self.min_samples

    def rank(self, models: list[ModelProfile], route: RoutingDecision, request: HydraRequest) -> list[ModelProfile]:
        return sorted(models, key=lambda m: self.expected(m, route, request)[0], reverse=True)


class ABRouter:
    """Deterministic traffic split between the heuristic and the learned policy."""

    def __init__(self, policy: LearnedRoutingPolicy, learned_fraction: float = 0.2) -> None:
        self.policy = policy
        self.learned_fraction = learned_fraction

    def arm_for(self, task_id: UUID) -> str:
        if not self.policy.ready() or self.learned_fraction <= 0:
            return "heuristic"
        h = int(hashlib.sha256(str(task_id).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return "learned" if h < self.learned_fraction else "heuristic"

    def apply(self, arm: str, ranked: list[ModelProfile], route: RoutingDecision,
              request: HydraRequest) -> list[ModelProfile]:
        return self.policy.rank(ranked, route, request) if arm == "learned" else ranked

    @staticmethod
    def report(runs: list[InferenceRun]) -> list[ArmStats]:
        per_task: dict[str, dict[UUID, InferenceRun]] = defaultdict(dict)
        for r in runs:
            if r.arm and r.role in GENERATION_ROLES:
                per_task[r.arm].setdefault(r.task_id, r)
        out = []
        for arm, tasks in sorted(per_task.items()):
            rs = list(tasks.values())
            conf = [r.task_confidence for r in rs if r.task_confidence is not None]
            qual = [r.quality for r in rs if r.quality is not None]
            out.append(ArmStats(arm=arm, tasks=len(rs),
                                mean_confidence=sum(conf) / len(conf) if conf else None,
                                mean_quality=sum(qual) / len(qual) if qual else None,
                                mean_latency_ms=sum(r.latency_ms for r in rs) / len(rs) if rs else None))
        return out
