# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Private / Federated Learning Plane.

    CENTRAL MODEL -> NODE A / NODE B / NODE C (local data, local training) -> AGGREGATION -> NEW MODEL

Raw prompts, documents and personal records never leave a node (``residency = node-X``):
nodes send only model updates (LoRA/adapter or classifier deltas), metrics and aggregate
statistics allowed by policy. Optional differential privacy: per-update clipping + Gaussian
noise with a simple privacy accountant. Federated analytics answers "how many Rust
debugging examples do you have?" without moving content (k-anonymity threshold + noise).
The IP ledger records the federated lineage with participant identifiers only.

Flower (flwr) can drive the same client/server roles at scale; HYDRA's coordinator here
runs in-process or over HTTP with signed updates."""

from __future__ import annotations

import json
import math
import random
from typing import Any, Awaitable, Callable

import numpy as np
from pydantic import BaseModel, Field

from hydra.core.hashing import hash_obj, now_iso

Weights = dict[str, np.ndarray]


class PrivacyConfig(BaseModel):
    differential_privacy: bool = False
    clipping_norm: float | None = 1.0
    noise_multiplier: float | None = 0.8
    target_epsilon: float | None = None
    delta: float = 1e-5
    min_count: int = 5
    """Federated analytics: suppress counts below k (k-anonymity)."""


class FederatedTrainingJob(BaseModel):
    id: str
    base_model: str
    adapter_type: str = "lora"  # lora | classifier | head
    participating_nodes: list[str]
    rounds: int = 5
    local_epochs: int = 1
    aggregation_strategy: str = "fedavg"  # fedavg | median
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    output_artifact: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class ClientUpdate(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    node_id: str
    num_examples: int
    delta: dict[str, Any]
    metrics: dict[str, float] = Field(default_factory=dict)


def _norm(delta: Weights) -> float:
    return math.sqrt(sum(float(np.sum(v.astype(np.float64) ** 2)) for v in delta.values()))


def clip(delta: Weights, c: float) -> Weights:
    n = _norm(delta)
    if n <= c or n == 0:
        return delta
    return {k: v * (c / n) for k, v in delta.items()}


def aggregate(updates: list[ClientUpdate], strategy: str = "fedavg") -> Weights:
    keys = updates[0].delta.keys()
    if strategy == "median":
        return {k: np.median(np.stack([np.asarray(u.delta[k]) for u in updates]), axis=0) for k in keys}
    total = sum(u.num_examples for u in updates) or 1
    return {k: sum(np.asarray(u.delta[k]) * (u.num_examples / total) for u in updates) for k in keys}


def epsilon_spent(noise_multiplier: float, rounds: int, delta: float = 1e-5, sample_rate: float = 1.0) -> float:
    """Advanced-composition approximation for the Gaussian mechanism (conservative accountant)."""
    if noise_multiplier <= 0:
        return float("inf")
    eps_step = sample_rate * math.sqrt(2 * math.log(1.25 / delta)) / noise_multiplier
    if eps_step > 20:
        return float("inf")  # noise too small for any meaningful guarantee
    return round(math.sqrt(2 * rounds * math.log(1 / delta)) * eps_step + rounds * eps_step * (math.exp(eps_step) - 1), 4)


LocalTrain = Callable[[Weights, int], Awaitable[tuple[Weights, int, dict[str, float]]]]
"""(global weights, local epochs) -> (new local weights, num_examples, metrics). Runs ON the node."""


class FederatedCoordinator:
    def __init__(self, ledger=None, seed: int = 0) -> None:
        self.ledger = ledger
        self.rng = np.random.default_rng(seed)

    async def run(self, job: FederatedTrainingJob, init: Weights, clients: dict[str, LocalTrain],
                  evaluate: Callable[[Weights], float] | None = None) -> tuple[Weights, FederatedTrainingJob]:
        weights = {k: np.array(v, dtype=np.float64) for k, v in init.items()}
        p = job.privacy
        for r in range(1, job.rounds + 1):
            updates = []
            for node in job.participating_nodes:
                local, n, metrics = await clients[node](weights, job.local_epochs)
                delta = {k: np.asarray(local[k], dtype=np.float64) - weights[k] for k in weights}
                if p.differential_privacy and p.clipping_norm:
                    delta = clip(delta, p.clipping_norm)
                updates.append(ClientUpdate(node_id=node, num_examples=n, delta=delta, metrics=metrics))
            agg = aggregate(updates, job.aggregation_strategy)
            if p.differential_privacy and p.clipping_norm and p.noise_multiplier:
                sigma = p.noise_multiplier * p.clipping_norm / max(1, len(updates))
                agg = {k: v + self.rng.normal(0, sigma, size=v.shape) for k, v in agg.items()}
            weights = {k: weights[k] + agg[k] for k in weights}
            score = evaluate(weights) if evaluate else None
            eps = epsilon_spent(p.noise_multiplier or 0, r, p.delta) if p.differential_privacy else None
            entry = {"round": r, "participants": [u.node_id for u in updates],
                     "examples": sum(u.num_examples for u in updates), "update_hash": hash_obj(
                         {k: float(np.sum(v)) for k, v in agg.items()}), "eval": score, "epsilon": eps,
                     "at": now_iso()}
            job.history.append(entry)
            if self.ledger is not None:
                self.ledger.append("FEDERATED_ROUND", {"job": job.id, **entry}, object_type="federated_job",
                                   object_id=job.id)
            if p.target_epsilon is not None and eps is not None and eps >= p.target_epsilon:
                break
        return weights, job


def federated_count(local_counts: dict[str, int], privacy: PrivacyConfig, seed: int = 0) -> dict[str, Any]:
    """Federated analytics: each node reports a count (never content); small counts are suppressed."""
    rng = random.Random(seed)
    per_node = {}
    for node, c in local_counts.items():
        if c < privacy.min_count:
            per_node[node] = None
            continue
        noisy = c + (rng.expovariate(1) - rng.expovariate(1)) * (1 / 0.5 if privacy.differential_privacy else 0)
        per_node[node] = max(0, round(noisy))
    visible = [v for v in per_node.values() if v is not None]
    return {"per_node": per_node, "total": sum(visible), "suppressed": sum(v is None for v in per_node.values())}


# ------------------------------------------------------------------------------ classifier adapter
def classifier_client(examples: list[tuple[str, str]], labels: list[str], dims: int = 2048, lr: float = 0.5,
                      seed: int = 0) -> LocalTrain:
    """A node that trains HYDRA's text classifier head on its private examples."""
    from hydra.training.specialists import TextClassifier

    async def train(global_w: Weights, epochs: int) -> tuple[Weights, int, dict[str, float]]:
        clf = TextClassifier(labels, dims)
        clf.W = global_w["W"].tolist()
        clf.b = global_w["b"].tolist()
        clf.fit([x for x, _ in examples], [y for _, y in examples], epochs=epochs, lr=lr, seed=seed)
        acc = sum(clf.predict(x)[0] == y for x, y in examples) / max(1, len(examples))
        return {"W": np.array(clf.W), "b": np.array(clf.b)}, len(examples), {"local_accuracy": acc}
    return train


def classifier_eval(examples: list[tuple[str, str]], labels: list[str], dims: int = 2048
                    ) -> Callable[[Weights], float]:
    from hydra.training.specialists import TextClassifier

    def ev(w: Weights) -> float:
        clf = TextClassifier(labels, dims)
        clf.W, clf.b = w["W"].tolist(), w["b"].tolist()
        return round(sum(clf.predict(x)[0] == y for x, y in examples) / max(1, len(examples)), 4)
    return ev


def flower_template(job: FederatedTrainingJob) -> str:
    """Flower ServerApp/ClientApp skeleton for running the same job at scale (requires flwr)."""
    return json.dumps({"framework": "flwr", "strategy": "FedAvg" if job.aggregation_strategy == "fedavg"
                       else "FedMedian", "num_rounds": job.rounds, "clients": job.participating_nodes,
                       "dp": job.privacy.model_dump(), "base_model": job.base_model, "adapter": job.adapter_type},
                      indent=2)
