# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Confidence is computed externally, never self-reported by a model.

C = 0.25 A + 0.20 V + 0.20 E + 0.15 T + 0.10 H + 0.10 K

A = agreement between models    V = verifier score       E = evidence strength
T = tool validation             H = model's historical accuracy
K = knowledge coverage (memory)
"""

from __future__ import annotations

from pydantic import BaseModel


class ConfidenceInputs(BaseModel):
    agreement: float | None = None
    verification: float | None = None
    evidence: float | None = None
    tool_validation: float | None = None
    historical_accuracy: float | None = None
    knowledge_coverage: float | None = None


WEIGHTS = {
    "agreement": 0.25,
    "verification": 0.20,
    "evidence": 0.20,
    "tool_validation": 0.15,
    "historical_accuracy": 0.10,
    "knowledge_coverage": 0.10,
}


def confidence_score(inputs: ConfidenceInputs) -> float:
    """Weighted mean over the signals that exist. Missing signals are not
    assumed good or bad: their weight is redistributed."""
    values = inputs.model_dump()
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return 0.5
    total_w = sum(WEIGHTS[k] for k in present)
    score = sum(WEIGHTS[k] * max(0.0, min(1.0, v)) for k, v in present.items()) / total_w
    # Few independent signals -> shrink toward 0.5 (less certainty about the certainty).
    return round(0.5 + (score - 0.5) * (0.8 + 0.2 * total_w), 4)
