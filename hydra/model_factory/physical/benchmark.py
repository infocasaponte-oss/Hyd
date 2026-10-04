# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Measured benchmark of a physical variant and hardware-gated selection."""
from __future__ import annotations

from pydantic import BaseModel, Field


class BenchmarkResult(BaseModel):
    variant_id: str
    profile: str
    prompt_tokens: int = Field(ge=0)
    generated_tokens: int = Field(ge=0)
    ttft_ms: float = Field(gt=0)
    tokens_per_second: float = Field(gt=0)
    peak_vram_mb: int = Field(ge=0)
    quality_score: float = Field(ge=0, le=1)
    passed: bool


def score_benchmark(result: BenchmarkResult, vram_limit_mb: int) -> float:
    if not result.passed or result.peak_vram_mb > vram_limit_mb:
        return float("-inf")
    return (
        result.quality_score * 100
        + min(result.tokens_per_second, 100) * 0.5
        - result.ttft_ms / 1000
        - result.peak_vram_mb / max(vram_limit_mb, 1) * 10
    )


def select_variant(
    results: list[BenchmarkResult], vram_limit_mb: int
) -> BenchmarkResult:
    if not results:
        raise ValueError("No benchmark results")
    winner = max(results, key=lambda item: score_benchmark(item, vram_limit_mb))
    if score_benchmark(winner, vram_limit_mb) == float("-inf"):
        raise ValueError("No benchmark candidate passed the hardware gate")
    return winner
