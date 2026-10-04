# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Epistemic planning: choose the action that buys the most information per unit of cost.

    IG(action) = H(B) - E_obs[ H(B | obs) ]

HYDRA plans not only actions but how to reduce uncertainty (active experimentation):
with H1 .46 / H2 .38 / H3 .16 it picks the experiment that best *discriminates*
the hypotheses, not necessarily the one that immediately fixes the problem."""

from __future__ import annotations

import math

from pydantic import BaseModel, Field


def entropy(p: dict[str, float]) -> float:
    return -sum(v * math.log2(v) for v in p.values() if v > 0)


def normalize(p: dict[str, float]) -> dict[str, float]:
    z = sum(p.values()) or 1.0
    return {k: v / z for k, v in p.items()}


class ExperimentProposal(BaseModel):
    id: str
    hypotheses: list[str]
    intervention: dict = Field(default_factory=dict)
    likelihoods: dict[str, dict[str, float]]
    """outcome -> {hypothesis: P(outcome | hypothesis)}"""
    cost: float = 0.1
    risk: float = 0.0
    reversible: bool = True
    information_gain: float = 0.0
    predicted_results: dict[str, float] = Field(default_factory=dict)


def expected_information_gain(prior: dict[str, float], likelihoods: dict[str, dict[str, float]]) -> float:
    prior = normalize(prior)
    h0 = entropy(prior)
    expected = 0.0
    for outcome, lik in likelihoods.items():
        p_obs = sum(prior[h] * lik.get(h, 0.0) for h in prior)
        if p_obs <= 0:
            continue
        post = normalize({h: prior[h] * lik.get(h, 0.0) for h in prior})
        expected += p_obs * entropy(post)
    return round(h0 - expected, 4)


def posterior(prior: dict[str, float], likelihoods: dict[str, dict[str, float]], outcome: str) -> dict[str, float]:
    lik = likelihoods[outcome]
    return {k: round(v, 4) for k, v in normalize({h: prior[h] * lik.get(h, 0.0) for h in prior}).items()}


def choose_experiment(prior: dict[str, float], proposals: list[ExperimentProposal], cost_weight: float = 0.5,
                      risk_weight: float = 1.0) -> list[ExperimentProposal]:
    """Rank experiments by IG - λc·cost - λr·risk (reversible first on ties)."""
    for p in proposals:
        p.information_gain = expected_information_gain(prior, p.likelihoods)
        p.predicted_results = {o: round(sum(normalize(prior)[h] * lik.get(h, 0) for h in prior), 4)
                               for o, lik in p.likelihoods.items()}
    return sorted(proposals, key=lambda p: (-(p.information_gain - cost_weight * p.cost - risk_weight * p.risk),
                                            not p.reversible))
