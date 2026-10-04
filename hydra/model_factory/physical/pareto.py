# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Pareto frontier of measured physical variants (quality, speed, latency, VRAM)."""
from __future__ import annotations

from hydra.model_factory.physical.benchmark import BenchmarkResult


def dominates(a: BenchmarkResult, b: BenchmarkResult) -> bool:
    no_worse = (
        a.quality_score >= b.quality_score
        and a.tokens_per_second >= b.tokens_per_second
        and a.ttft_ms <= b.ttft_ms
        and a.peak_vram_mb <= b.peak_vram_mb
    )
    strictly_better = (
        a.quality_score > b.quality_score
        or a.tokens_per_second > b.tokens_per_second
        or a.ttft_ms < b.ttft_ms
        or a.peak_vram_mb < b.peak_vram_mb
    )
    return no_worse and strictly_better


def pareto_frontier(
    results: list[BenchmarkResult], vram_limit_mb: int
) -> list[BenchmarkResult]:
    eligible = [
        result
        for result in results
        if result.passed and result.peak_vram_mb <= vram_limit_mb
    ]
    return [
        candidate
        for candidate in eligible
        if not any(
            dominates(other, candidate)
            for other in eligible
            if other is not candidate
        )
    ]
