# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Promotion of a benchmarked physical variant (checksums and lineage required)."""
from __future__ import annotations

from hydra.model_factory.contracts import BuildState, ModelVariant


class PromotionDenied(ValueError):
    pass


def promote(variant: ModelVariant, *, benchmark_passed: bool) -> ModelVariant:
    if variant.state != BuildState.BENCHMARKED:
        raise PromotionDenied("Variant must be benchmarked before promotion")
    if not benchmark_passed:
        raise PromotionDenied("Benchmark gate did not pass")
    if not variant.artifact_sha256 or len(variant.artifact_sha256) != 64:
        raise PromotionDenied("Artifact checksum is required")
    lineage = variant.lineage
    if not lineage.base_model_sha256 or len(lineage.base_model_sha256) != 64:
        raise PromotionDenied("Base model checksum is required")
    if lineage.dataset_id and not lineage.dataset_manifest_sha256:
        raise PromotionDenied("Dataset lineage hash is required")
    variant.state = BuildState.PROMOTED
    return variant
