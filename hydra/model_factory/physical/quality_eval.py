# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Quality of model outputs against a benchmark suite."""
from __future__ import annotations

from dataclasses import dataclass

from hydra.model_factory.physical.benchmark_suite import BenchmarkCase


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    score: float
    passed: bool


def score_case(case: BenchmarkCase, output: str) -> CaseScore:
    normalized = output.casefold()
    expected = [item.casefold() for item in case.expected_contains]
    if not expected:
        return CaseScore(case.case_id, 1.0, True)
    hits = sum(item in normalized for item in expected)
    score = hits / len(expected)
    return CaseScore(case.case_id, score, score == 1.0)


def weighted_quality(cases: list[BenchmarkCase], outputs: list[str]) -> float:
    if len(cases) != len(outputs) or not cases:
        raise ValueError("Cases and outputs must be non-empty and aligned")
    total_weight = sum(case.weight for case in cases)
    return sum(
        score_case(case, output).score * case.weight
        for case, output in zip(cases, outputs, strict=True)
    ) / total_weight
