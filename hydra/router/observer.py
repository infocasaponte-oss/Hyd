# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded local decision experiment; it cannot modify the routing policy."""
from __future__ import annotations

import asyncio
import time

from hydra.core.contracts import DecisionObservation, ExecutionMode, HydraRequest, TaskType
from hydra.providers.decision import LocalSystemOneProvider, validate_answers
from hydra.training.calibrator import TemperatureCalibrator


class DecisionObserver:
    def __init__(self, provider: LocalSystemOneProvider, timeout_s: float = 0.5,
                 calibrator: TemperatureCalibrator | None = None, criteria: dict[str, str] | None = None):
        if not 0 < timeout_s <= 5:
            raise ValueError("observation timeout must be in (0, 5]")
        self.provider = provider
        self.model = provider.model
        self.timeout_s = timeout_s
        self.calibrator = calibrator
        self.criteria = dict(criteria) if criteria is not None else {
            task.value: f"The user requests a {task.value} task" for task in TaskType}
        self.expected_run: str | None = calibrator.model_run if calibrator else None

    async def observe(self, request: HydraRequest) -> DecisionObservation:
        base = {"model": self.provider.model}
        gate = policy_gate(request.last_user_text)
        if gate is not None:
            return DecisionObservation(status="observed", model="hydra-policy-v2", reason=gate[1],
                                       selected=gate[0], probabilities={gate[0]: 1.0}, confidence=1.0)
        # Explicit latency budgets belong entirely to the actual execution.
        reason = ("private" if request.private else "fast" if request.mode == ExecutionMode.FAST
                  else "latency_budget" if request.max_latency_ms is not None else None)
        if reason:
            return DecisionObservation(status="skipped", reason=reason, **base)
        questions = {"task": {"type": "choice", "criteria": self.criteria}}
        start = time.perf_counter()
        try:
            if self.expected_run:
                await self._verify_run()
            payload = await asyncio.wait_for(
                self.provider.decide(request.last_user_text, questions), self.timeout_s)
            if payload.get("model") != self.provider.model:
                raise ValueError("model alias mismatch")
            answer = validate_answers(questions, payload)["answers"]["task"]
            if self.calibrator is not None:
                answer = self.calibrator.apply(answer)
            if self.expected_run:
                await self._verify_run()
            return DecisionObservation(
                status="observed", selected=answer["choice"],
                probabilities=answer["probabilities"], confidence=answer["confidence"],
                elapsed_ms=(time.perf_counter() - start) * 1000, **base)
        except Exception as exc:
            # Do not copy server errors or user content into telemetry.
            return DecisionObservation(
                status="timeout" if isinstance(exc, TimeoutError) else "error",
                reason=type(exc).__name__, elapsed_ms=(time.perf_counter() - start) * 1000, **base)

    async def close(self) -> None:
        await self.provider.close()

    async def _verify_run(self) -> None:
        response = await self.provider.client.get("/v1/models", timeout=self.timeout_s)
        response.raise_for_status()
        card = next(c for c in response.json()["models"] if c["name"] == self.model)
        if card.get("run") != self.expected_run:
            raise ValueError("decision checkpoint changed")


def policy_gate(text: str) -> tuple[str, str] | None:
    """Deterministic safety outcomes for classes absent from Kev's pointer head."""
    lowered = text.casefold()
    high_risk = ("producción", "production", "borra la base", "drop table", "pago irreversible",
                 "acción médica", "acción medica", "permisos de administrador")
    security = ("phishing", "credenciales", "exfiltración", "exfiltracion", "comando peligroso")
    privacy = ("dato personal", "anonimiza", "anonimizar", "borrar mis datos", "privacidad")
    ambiguous = ("haz eso", "continúa con lo anterior", "continua con lo anterior", "sin información",
                 "sin informacion", "decide entre todas", "concede permisos aunque")
    if any(term in lowered for term in high_risk):
        return "review", "policy_gate.high_risk_review"
    if any(term in lowered for term in security):
        return "security", "policy_gate.security"
    if any(term in lowered for term in privacy):
        return "privacy", "policy_gate.privacy"
    if not lowered.strip() or any(term in lowered for term in ambiguous):
        return "abstain", "policy_gate.abstain"
    return None
