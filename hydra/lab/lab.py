# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Lab: controlled self-improvement, never "the agent rewrites itself in production".

production telemetry -> new policies / prompts / routers / models -> benchmarks
-> shadow traffic -> canary (5% -> 20% -> 100%) -> promotion | automatic rollback
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.contracts import HydraRequest, HydraResponse
from hydra.core.events import EventType, HydraEvent

log = logging.getLogger("hydra.lab")

CANARY_STEPS = (0.05, 0.20, 1.0)


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    BENCHMARKING = "benchmarking"
    SHADOW = "shadow"
    CANARY = "canary"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


class ArmMetrics(BaseModel):
    n: int = 0
    confidence_sum: float = 0.0
    latency_sum: float = 0.0
    verified: int = 0
    failures: int = 0

    def add(self, resp: HydraResponse | None) -> None:
        self.n += 1
        if resp is None:
            self.failures += 1
            return
        self.confidence_sum += resp.meta.confidence
        self.latency_sum += resp.meta.latency_ms
        self.verified += int(resp.meta.verified)

    @property
    def confidence(self) -> float:
        ok = self.n - self.failures
        return self.confidence_sum / ok if ok else 0.0

    @property
    def latency(self) -> float:
        ok = self.n - self.failures
        return self.latency_sum / ok if ok else 0.0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.n if self.n else 0.0

    def summary(self) -> dict:
        return {"n": self.n, "confidence": round(self.confidence, 4), "latency_ms": round(self.latency, 1),
                "verified_rate": round(self.verified / self.n, 4) if self.n else 0.0,
                "failure_rate": round(self.failure_rate, 4)}


class Gates(BaseModel):
    benchmark_tolerance: float = 0.02
    confidence_tolerance: float = 0.02
    latency_increase: float = 0.25
    failure_increase: float = 0.02
    shadow_samples: int = 20
    canary_samples: int = 30


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: f"exp-{uuid.uuid4().hex[:8]}")
    name: str
    kind: str  # policy | prompt | router | model | config
    description: str = ""
    overrides: dict[str, Any]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    canary_step: int = 0
    gates: Gates = Field(default_factory=Gates)
    benchmark: dict[str, Any] = Field(default_factory=dict)
    baseline: ArmMetrics = Field(default_factory=ArmMetrics)
    candidate: ArmMetrics = Field(default_factory=ArmMetrics)
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def canary_fraction(self) -> float:
        return CANARY_STEPS[min(self.canary_step, len(CANARY_STEPS) - 1)]

    def log(self, event: str, **data) -> None:
        self.history.append({"at": datetime.now(UTC).isoformat(), "event": event, **data})


class HydraLab:
    def __init__(self, kernel, evaluator=None, path: Path | None = None, bus=None, docs=None) -> None:
        """Experiments persist in the ``lab.json`` document (``hydra.core.docstore``). Live arm metrics
        are measured by the node that serves the traffic; each save stores that node's view of the
        experiment it changed."""
        self.kernel = kernel
        self.evaluator = evaluator
        self.path = path
        self.bus = bus
        self.experiments: dict[str, Experiment] = {}
        self._registry = None
        if path is not None:
            from hydra.core.docstore import DocumentStore, KeyedModels

            self._registry = KeyedModels((docs or DocumentStore()).document("lab.json", path), Experiment)
        self._background: set[asyncio.Task] = set()
        self._load()

    # ------------------------------------------------------------------ lifecycle
    def create(self, name: str, kind: str, overrides: dict[str, Any], description: str = "",
               gates: Gates | None = None) -> Experiment:
        self.kernel.config.merged(overrides)  # validates the override keys early
        exp = Experiment(name=name, kind=kind, overrides=overrides, description=description,
                         gates=gates or Gates())
        exp.log("created")
        self.experiments[exp.id] = exp
        self._save(exp)
        return exp

    def candidate_kernel(self, exp: Experiment):
        return self.kernel.with_config(**exp.overrides)

    async def run_benchmark(self, exp_id: str, suites: list[str] | None = None) -> Experiment:
        """Offline benchmark of baseline vs candidate on HYDRA's eval suites (shadow mode: no side effects)."""
        exp = self.experiments[exp_id]
        exp.status = ExperimentStatus.BENCHMARKING
        if self.evaluator is None:
            exp.status = ExperimentStatus.SHADOW
            exp.log("benchmark skipped (no evaluator)")
            self._save(exp)
            return exp
        base = await self.evaluator.run_kernel(self.kernel, suites, label="baseline", shadow=True, learn=False)
        cand = await self.evaluator.run_kernel(self.candidate_kernel(exp), suites, label=exp.id,
                                               shadow=True, learn=False)
        exp.benchmark = {"baseline": base.overall, "candidate": cand.overall,
                         "baseline_suites": {k: v.score for k, v in base.suites.items()},
                         "candidate_suites": {k: v.score for k, v in cand.suites.items()}}
        if cand.overall + exp.gates.benchmark_tolerance >= base.overall:
            exp.status = ExperimentStatus.SHADOW
            exp.log("benchmark passed", **exp.benchmark)
        else:
            exp.status = ExperimentStatus.REJECTED
            exp.log("benchmark failed", **exp.benchmark)
        await self._notify(exp)
        self._save(exp)
        return exp

    # ------------------------------------------------------------------ serving
    def _bucket(self, key: str) -> float:
        return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

    def pick(self, task_key: str):
        """Canary routing: returns (kernel, experiment or None, arm)."""
        for exp in self.experiments.values():
            if exp.status == ExperimentStatus.CANARY and self._bucket(exp.id + task_key) < exp.canary_fraction:
                return self.candidate_kernel(exp), exp, "candidate"
        canary = next((e for e in self.experiments.values() if e.status == ExperimentStatus.CANARY), None)
        return self.kernel, canary, "baseline"

    async def serve(self, request: HydraRequest, task_id=None) -> HydraResponse:
        """Production entry point: canary split + shadow copies for experiments in shadow."""
        key = str(task_id or uuid.uuid4())
        kernel, exp, arm = self.pick(key)
        try:
            resp = await kernel.run(request, task_id=task_id)
        except Exception:
            if exp is not None:
                (exp.candidate if arm == "candidate" else exp.baseline).add(None)
                await self.evaluate(exp.id)
            raise
        if exp is not None:
            (exp.candidate if arm == "candidate" else exp.baseline).add(resp)
            await self.evaluate(exp.id)
        for sexp in [e for e in self.experiments.values() if e.status == ExperimentStatus.SHADOW]:
            sexp.baseline.add(resp)
            self._spawn(self._shadow(sexp, request))
        return resp

    async def _shadow(self, exp: Experiment, request: HydraRequest) -> None:
        try:
            resp = await self.candidate_kernel(exp).run(request.model_copy(update={"use_cache": False}),
                                                        shadow=True, learn=False)
        except Exception:
            resp = None
        exp.candidate.add(resp)
        await self.evaluate(exp.id)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def drain(self) -> None:
        """Wait for pending shadow executions (tests, shutdown)."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    # ------------------------------------------------------------------ gates
    def _degraded(self, exp: Experiment) -> str | None:
        b, c, g = exp.baseline, exp.candidate, exp.gates
        if c.confidence + g.confidence_tolerance < b.confidence:
            return f"confidence {c.confidence:.3f} < baseline {b.confidence:.3f}"
        if b.latency and c.latency > b.latency * (1 + g.latency_increase):
            return f"latency {c.latency:.0f} ms > baseline {b.latency:.0f} ms"
        if c.failure_rate > b.failure_rate + g.failure_increase:
            return f"failure rate {c.failure_rate:.3f} > baseline {b.failure_rate:.3f}"
        return None

    async def evaluate(self, exp_id: str) -> Experiment:
        exp = self.experiments[exp_id]
        g = exp.gates
        if exp.status == ExperimentStatus.SHADOW and exp.candidate.n >= g.shadow_samples:
            if reason := self._degraded(exp):
                exp.status = ExperimentStatus.REJECTED
                exp.log("shadow failed", reason=reason, baseline=exp.baseline.summary(),
                        candidate=exp.candidate.summary())
            else:
                exp.status = ExperimentStatus.CANARY
                exp.canary_step = 0
                exp.log("shadow passed -> canary", fraction=exp.canary_fraction,
                        baseline=exp.baseline.summary(), candidate=exp.candidate.summary())
                exp.baseline, exp.candidate = ArmMetrics(), ArmMetrics()
            await self._notify(exp)
        elif exp.status == ExperimentStatus.CANARY:
            if exp.candidate.n >= 5 and (reason := self._degraded(exp)):
                exp.status = ExperimentStatus.ROLLED_BACK
                exp.log("automatic rollback", reason=reason, fraction=exp.canary_fraction,
                        baseline=exp.baseline.summary(), candidate=exp.candidate.summary())
                await self._notify(exp)
            elif exp.candidate.n >= g.canary_samples:
                if exp.canary_step + 1 < len(CANARY_STEPS):
                    exp.canary_step += 1
                    exp.log("canary step", fraction=exp.canary_fraction, candidate=exp.candidate.summary())
                    exp.baseline, exp.candidate = ArmMetrics(), ArmMetrics()
                else:
                    self.promote(exp.id)
                await self._notify(exp)
        self._save(exp)
        return exp

    def promote(self, exp_id: str) -> Experiment:
        exp = self.experiments[exp_id]
        self.kernel.apply_config(self.kernel.config.merged(exp.overrides))
        exp.status = ExperimentStatus.PROMOTED
        exp.log("promoted", overrides=exp.overrides)
        self._save(exp)
        return exp

    def rollback(self, exp_id: str, reason: str = "manual") -> Experiment:
        exp = self.experiments[exp_id]
        exp.status = ExperimentStatus.ROLLED_BACK
        exp.log("rolled back", reason=reason)
        self._save(exp)
        return exp

    def start_shadow(self, exp_id: str) -> Experiment:
        exp = self.experiments[exp_id]
        exp.status = ExperimentStatus.SHADOW
        exp.log("shadow started")
        self._save(exp)
        return exp

    # ------------------------------------------------------------------ persistence
    async def _notify(self, exp: Experiment) -> None:
        if self.bus is not None:
            await self.bus.publish(HydraEvent(task_id=uuid.UUID(int=0), type=EventType.LAB_UPDATED, source="lab",
                                              payload={"experiment": exp.id, "status": exp.status.value}))

    def _save(self, exp: Experiment | None = None) -> None:
        if self._registry is None:
            return
        for e in ([exp] if exp is not None else list(self.experiments.values())):
            self._registry.put(e.id, e)

    def _load(self) -> None:
        if self._registry is None:
            return
        for k, v in self._registry.all().items():
            self.experiments[k] = v.model_copy(deep=True)
        for exp in self.experiments.values():
            if exp.status == ExperimentStatus.PROMOTED:
                self.kernel.apply_config(self.kernel.config.merged(exp.overrides))
