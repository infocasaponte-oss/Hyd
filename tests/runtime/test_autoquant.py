# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.autoquant import AutoQuant, HardwareTarget
from hydra.runtime.benchmarking import BenchmarkResult
from hydra.runtime.optimization_report import OptimizationReportStore


def candidate(name: str) -> BenchmarkResult:
    return BenchmarkResult(
        variant_id=name,
        profile=name,
        prompt_tokens=32,
        generated_tokens=32,
        ttft_ms=100,
        tokens_per_second=40,
        peak_vram_mb=7000,
        quality_score=0.8,
        passed=True,
    )


def test_unmeasured_report_never_selects_winner(tmp_path):
    report = AutoQuant().summarize(
        hardware=HardwareTarget("NVIDIA GeForce RTX 3060 Ti", 8192),
        results=[candidate("q4")],
        measured=False,
    )
    assert report.selected_variant_id is None
    stored = OptimizationReportStore(tmp_path).put(report)
    assert len(stored.report_hash) == 64


def test_measured_report_can_select_candidate():
    report = AutoQuant().summarize(
        hardware=HardwareTarget("NVIDIA GeForce RTX 3060 Ti", 8192),
        results=[candidate("q4")],
        measured=True,
    )
    assert report.selected_variant_id == "q4"
