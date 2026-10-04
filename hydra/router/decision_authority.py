# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Narrow, fail-closed authority gate for learned routing decisions."""
from dataclasses import dataclass
import math
from typing import Any

from hydra.core.contracts import DecisionObservation, TaskType


@dataclass(frozen=True)
class DecisionAuthority:
    enabled: bool
    model: str
    min_confidence: float = .95

    @classmethod
    def from_evidence(cls, evidence: dict[str, Any], model: str):
        # Deployment evidence must describe an independent, complete evaluation,
        # not training accuracy or a repeatedly tuned regression benchmark.
        measures = ("accuracy", "accuracy_wilson_lower_95", "coverage", "ece_10_bins")
        if any(type(evidence.get(key)) not in (int, float)
               or not math.isfinite(evidence[key]) or not 0 <= evidence[key] <= 1 for key in measures):
            return cls(False, model)
        enabled = (evidence.get("model") == model and evidence.get("independent_test") is True
                   and evidence.get("complete") is True and evidence.get("accuracy", 0) > .90
                   and evidence.get("accuracy_wilson_lower_95", 0) >= .90
                   and evidence["accuracy_wilson_lower_95"] <= evidence["accuracy"]
                   and evidence.get("coverage", 0) >= .80
                   and 0 <= evidence.get("ece_10_bins", 1) <= .10
                   and evidence.get("calibration_model_bound") is True
                   and bool(evidence.get("model_revision")))
        return cls(enabled, model)

    def task_hint(self, observation: DecisionObservation) -> TaskType | None:
        if (not self.enabled or observation.model != self.model or observation.status != "observed"
                or (observation.confidence or 0) < self.min_confidence):
            return None
        # No authority over tools, privacy, permissions or irreversible actions.
        allowed = {t.value: t for t in (TaskType.CHAT, TaskType.CODING, TaskType.REASONING,
                                       TaskType.RESEARCH, TaskType.VISION)}
        return allowed.get(observation.selected)
