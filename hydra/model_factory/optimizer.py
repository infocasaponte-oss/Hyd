# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Pareto frontier over (quality up, speed up, memory down) and winner selection.

A variant dominated on every axis (e.g. Q6 when Q8 is better and Q5 is almost as good
and much smaller) is never deployed.
"""

from __future__ import annotations

from pydantic import BaseModel

from hydra.model_factory.hardware import HardwareProfile
from hydra.model_factory.manifest import ModelVariant


QUALITY_EPSILON = 0.005
"""Quality differences below this are noise: "almost the same quality" does not save a variant."""


def dominates(a: ModelVariant, b: ModelVariant, eps: float = QUALITY_EPSILON) -> bool:
    ge = (a.quality_score >= b.quality_score - eps and a.tokens_per_second >= b.tokens_per_second
          and a.memory_gb <= b.memory_gb)
    gt = (a.quality_score > b.quality_score or a.tokens_per_second > b.tokens_per_second
          or a.memory_gb < b.memory_gb)
    return ge and gt


def pareto_frontier(variants: list[ModelVariant], eps: float = QUALITY_EPSILON) -> list[ModelVariant]:
    return [v for v in variants if not any(dominates(o, v, eps) for o in variants if o is not v)]


class Selection(BaseModel):
    winner: ModelVariant | None
    frontier: list[str]
    dominated: list[str]
    rejected: list[str]
    reason: str


def choose_winner(variants: list[ModelVariant], quality_min: float | None = None,
                  hardware: HardwareProfile | None = None, reference_quality: float | None = None) -> Selection:
    approved = [v for v in variants if v.approved]
    rejected = [v.id for v in variants if not v.approved]
    frontier = pareto_frontier(approved)
    dominated = [v.id for v in approved if v not in frontier]
    pool = list(frontier)
    if hardware is not None:
        pool = [v for v in pool if v.memory_gb <= hardware.memory_budget_gb] or pool
    if quality_min is not None:
        floor = quality_min * (reference_quality or 1.0)
        good = [v for v in pool if v.quality_score >= floor]
        if good:
            winner = max(good, key=lambda v: (v.tokens_per_second, -v.memory_gb))
            return Selection(winner=winner, frontier=[v.id for v in frontier], dominated=dominated,
                             rejected=rejected, reason=f"fastest variant with quality >= {floor:.3f}")
    if not pool:
        return Selection(winner=None, frontier=[], dominated=dominated, rejected=rejected,
                         reason="no approved variant")
    winner = max(pool, key=lambda v: (round(v.quality_score, 3), v.tokens_per_second))
    return Selection(winner=winner, frontier=[v.id for v in frontier], dominated=dominated, rejected=rejected,
                     reason="highest quality on the frontier (quality floor not reachable)")
