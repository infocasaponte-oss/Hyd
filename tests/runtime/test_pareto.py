# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.benchmarking import BenchmarkResult
from hydra.runtime.pareto import pareto_frontier


def result(name, quality, speed, ttft, vram):
    return BenchmarkResult(
        variant_id=name,
        profile=name,
        prompt_tokens=10,
        generated_tokens=20,
        ttft_ms=ttft,
        tokens_per_second=speed,
        peak_vram_mb=vram,
        quality_score=quality,
        passed=True,
    )


def test_dominated_candidate_removed():
    strong = result("strong", 0.9, 50, 100, 6000)
    weak = result("weak", 0.8, 40, 120, 6500)
    assert [x.variant_id for x in pareto_frontier([strong, weak], 8192)] == ["strong"]


def test_tradeoff_candidates_survive():
    quality = result("quality", 0.95, 35, 130, 7000)
    speed = result("speed", 0.85, 55, 90, 6200)
    names = {x.variant_id for x in pareto_frontier([quality, speed], 8192)}
    assert names == {"quality", "speed"}
