# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.benchmark_suite import RTX3060TI_ALPHA_SUITE
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.physical_registry import PhysicalModelRegistry
from hydra.runtime.quality_eval import weighted_quality


def variant(state: BuildState) -> ModelVariant:
    return ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=state,
    )


def test_suite_is_versioned_and_hashed():
    assert len(RTX3060TI_ALPHA_SUITE.suite_hash) == 64


def test_quality_requires_expected_content():
    suite = RTX3060TI_ALPHA_SUITE
    score = weighted_quality(suite.cases, ["703", "The system is ready.", '{"ok": true}'])
    assert score == 1.0


def test_registry_rejects_unpromoted_variant():
    registry = PhysicalModelRegistry()
    try:
        registry.register(variant(BuildState.BENCHMARKED))
    except ValueError:
        pass
    else:
        raise AssertionError("unpromoted variant entered registry")


def test_registry_resolves_promoted_variant():
    registry = PhysicalModelRegistry()
    model = variant(BuildState.PROMOTED)
    registry.register(model)
    assert registry.resolve().variant_id == model.variant_id
