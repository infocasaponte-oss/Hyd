# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.benchmarking import BenchmarkResult, select_variant
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.promotion import PromotionDenied, promote
from hydra.runtime.quant_profiles import profiles_for


def test_3060ti_profiles_include_real_quant_candidates():
    profiles = profiles_for("NVIDIA GeForce RTX 3060 Ti", 8192)
    assert {p.quantization for p in profiles} == {"Q4_K_M", "Q5_K_M"}


def test_benchmark_selection_rejects_vram_overflow():
    results = [
        BenchmarkResult(
            variant_id="a", profile="quality", prompt_tokens=10, generated_tokens=10,
            ttft_ms=100, tokens_per_second=50, peak_vram_mb=9000,
            quality_score=0.9, passed=True,
        ),
        BenchmarkResult(
            variant_id="b", profile="balanced", prompt_tokens=10, generated_tokens=10,
            ttft_ms=120, tokens_per_second=40, peak_vram_mb=7000,
            quality_score=0.85, passed=True,
        ),
    ]
    assert select_variant(results, 8192).variant_id == "b"


def test_promotion_requires_dataset_lineage_hash():
    lineage = ModelLineage(
        base_model="base",
        base_model_sha256="a" * 64,
        dataset_id=uuid4(),
    )
    variant = ModelVariant(
        lineage=lineage,
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.BENCHMARKED,
    )
    with pytest.raises(PromotionDenied):
        promote(variant, benchmark_passed=True)
