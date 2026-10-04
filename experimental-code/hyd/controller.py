# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""In-process Hyd observer; authority binds model, features and calibration bytes."""
from __future__ import annotations

import hashlib
import asyncio
import json
import time
from pathlib import Path

from hydra.core.contracts import DecisionObservation, HydraRequest, TaskType
from hydra.hyd.engine import HydEngine
from hydra.hyd.model import CandidateRanker
from hydra.router.decision_authority import DecisionAuthority
from hydra.router.decision_contract import CRITERIA
from hydra.router.observer import policy_gate


class HydBusyError(RuntimeError):
    pass


def implementation_digest() -> str:
    digest = hashlib.sha256()
    for name in ("model.py", "engine.py", "controller.py", "neural.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


class HydController:
    model = "hyd-latest"

    def __init__(self, model_path: Path, calibration_path: Path, evidence_path: Path | None = None):
        metadata = json.loads(model_path.read_text(encoding="utf-8"))
        if metadata.get("format") == "hyd-contextual-ranker/1":
            from hydra.hyd.neural import ContextRanker
            ranker = ContextRanker.load(model_path)
        else:
            ranker = CandidateRanker.load(model_path)
        raw = calibration_path.read_bytes()
        calibration = json.loads(raw)
        if (calibration.get("format") != "hyd-calibration/1"
                or calibration.get("model_sha256") != ranker.revision
                or calibration.get("implementation_sha256") != implementation_digest()
                or calibration.get("temperature") != ranker.temperature
                or calibration.get("criteria") != CRITERIA
                or not calibration.get("dataset_sha256")):
            raise ValueError("Hyd calibration does not match the model and implementation")
        self.engine = HydEngine(ranker, calibration["min_confidence"], calibration["min_margin"])
        self.authority = DecisionAuthority(False, self.model)
        self.calibration_revision = hashlib.sha256(raw).hexdigest()
        self._active = None
        if evidence_path:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            bound = (evidence.get("format") == "hyd-authority/1"
                     and evidence.get("model_revision") == ranker.revision
                     and evidence.get("implementation_sha256") == implementation_digest()
                     and evidence.get("calibration_sha256") == self.calibration_revision
                     and evidence.get("threshold") == self.engine.min_confidence
                     and evidence.get("margin") == self.engine.min_margin)
            if not bound:
                raise ValueError("Hyd authority evidence belongs to another runtime")
            self.authority = DecisionAuthority.from_evidence(evidence, self.model)

    async def observe(self, request: HydraRequest) -> DecisionObservation:
        start = time.perf_counter()
        gate = policy_gate(request.last_user_text)
        if gate:
            return DecisionObservation(status="observed", model="hydra-policy-v2", reason=gate[1],
                                       selected=gate[0], probabilities={gate[0]: 1}, confidence=1)
        if request.max_latency_ms is not None:
            return DecisionObservation(status="skipped", model=self.model, reason="latency_budget")
        try:
            answer = (await self.decide(request.last_user_text,
                {"task": {"type": "choice", "criteria": CRITERIA}}))["answers"]["task"]
            return DecisionObservation(status="observed", model=self.model,
                selected="abstain" if answer["abstained"] else answer["choice"],
                probabilities=answer["probabilities"], confidence=answer["selection_probability"],
                reason="hyd." + answer["reason"], elapsed_ms=(time.perf_counter() - start) * 1000)
        except (ValueError, TypeError, OverflowError, RuntimeError, TimeoutError):
            return DecisionObservation(status="error", model=self.model, reason="hyd.invalid_input",
                                       elapsed_ms=(time.perf_counter() - start) * 1000)

    def task_hint(self, observation: DecisionObservation) -> TaskType | None:
        return self.authority.task_hint(observation)

    async def decide(self, state, questions, timeout_s: float = 5):
        # One running computation, no queued GPU work. A timed-out thread keeps
        # its slot until completion; cancellation must not create hidden backlog.
        if not 0 < timeout_s <= 60:
            raise ValueError("invalid Hyd deadline")
        if self._active is not None and not self._active.done():
            raise HydBusyError("Hyd decision capacity is busy")
        self._active = asyncio.create_task(asyncio.to_thread(self.engine.decide, state, questions, time.monotonic() + timeout_s))
        self._active.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return await asyncio.wait_for(asyncio.shield(self._active), timeout=timeout_s)

    async def close(self):
        if self._active is not None:
            try:
                await asyncio.shield(self._active)
            except (ValueError, TypeError, OverflowError, RuntimeError):
                pass
