# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model scoring.

S(m) = wq*Q + ws*S + wp*P - wl*L - wc*C - wr*R - load

Q = historical (learned) quality, S = specialization, P = privacy,
L = latency, C = cost, R = risk/error rate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from hydra.core.contracts import ExecutionMode, HydraRequest, RoutingDecision

if TYPE_CHECKING:
    from hydra.registry.models import ModelProfile


SOURCE_SIGNAL = "source.grounded"
"""Router signal: the latest message supplies source material (legal articles or code)."""


class ScoringWeights(BaseModel):
    quality: float = 0.45
    specialization: float = 0.20
    privacy: float = 0.05
    latency: float = 0.15
    cost: float = 0.10
    risk: float = 0.05
    load: float = 0.20


MODE_WEIGHTS: dict[ExecutionMode, ScoringWeights] = {
    ExecutionMode.FAST: ScoringWeights(quality=0.30, latency=0.45, cost=0.15),
    ExecutionMode.BALANCED: ScoringWeights(),
    ExecutionMode.DEEP: ScoringWeights(quality=0.60, latency=0.05, cost=0.05),
    ExecutionMode.MAX: ScoringWeights(quality=0.75, latency=0.0, cost=0.0),
    ExecutionMode.PRIVATE: ScoringWeights(privacy=0.5),
}


def normalize_latency(model: ModelProfile) -> float:
    return min(model.predicted_latency_ms / 10_000, 1.0)


def estimate_cost(model: ModelProfile, request: HydraRequest | None) -> float:
    tokens_in = len(request.text) // 4 if request else 1000
    cost = model.estimate_cost(tokens_in, 1000)
    return min(cost / 0.05, 1.0)  # 5 cents per call saturates the penalty


def specialization(model: ModelProfile, route: RoutingDecision) -> float:
    s = model.capabilities.for_task(route.task_type)
    if route.requires_reasoning:
        s = (s + model.capabilities.reasoning) / 2
    if route.requires_tools:
        s = (s + model.capabilities.tools) / 2
    if route.requires_vision:
        s = (s + model.capabilities.vision) / 2
    return s


def risk_score(model: ModelProfile, route: RoutingDecision) -> float:
    # Weaker models are riskier on risky tasks.
    return route.risk * (1 - model.quality(route.task_type))


def score_model(
    model: ModelProfile,
    route: RoutingDecision,
    request: HydraRequest | None = None,
    weights: ScoringWeights | None = None,
) -> float:
    if weights is None:
        weights = MODE_WEIGHTS[request.mode] if request else ScoringWeights()
    return (
        weights.quality * model.quality(route.task_type)
        + weights.specialization * specialization(model, route)
        + weights.privacy * (1.0 if model.local else 0.0)
        - weights.latency * normalize_latency(model)
        - weights.cost * estimate_cost(model, request)
        - weights.risk * risk_score(model, route)
        - weights.load * model.current_load
    )


def filter_models(
    models: list[ModelProfile],
    request: HydraRequest,
    route: RoutingDecision,
) -> list[ModelProfile]:
    """Hard constraints before scoring. Privacy is enforced by code, never by prompt."""
    candidates = []
    # Older turns are compressed by the context compiler; the latest message must fit as-is.
    needed_ctx = len(request.last_user_text) // 3
    for model in models:
        if not model.enabled:
            continue
        if request.private and not model.local:
            continue
        if route.requires_vision and model.capabilities.vision < 0.5:
            continue
        if route.requires_tools and model.capabilities.tools < 0.5:
            continue
        if model.context_window < needed_ctx:
            continue
        candidates.append(model)
    # Grounded specialists never answer requests without their own source; with a source they are
    # ranked first (rank_models) and the generalists stay behind them as the runtime fallback.
    if route.signals.get(SOURCE_SIGNAL, 0) > 0:
        return candidates
    return [m for m in candidates if m.specialty != "grounded"]


def _preferred_specialist(model: ModelProfile, route: RoutingDecision) -> bool:
    return model.specialty == "grounded" and route.signals.get(SOURCE_SIGNAL, 0) > 0


def rank_models(
    models: list[ModelProfile],
    route: RoutingDecision,
    request: HydraRequest | None = None,
) -> list[ModelProfile]:
    return sorted(
        (m for m in models if m.enabled),
        key=lambda m: (_preferred_specialist(m, route), score_model(m, route, request)),
        reverse=True,
    )
