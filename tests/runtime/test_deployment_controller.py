# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_controller import DeploymentController, EvidenceRejected
from hydra.runtime.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.runtime.deployment_evidence_store import DeploymentEvidenceStore
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.runtime_evidence import RuntimeEvidenceStore


def deployment() -> Deployment:
    model = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )
    return Deployment(model, {"reasoning.general"}, generation=1)


def test_shadow_needs_evidence():
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    controller = DeploymentController(registry)
    controller.begin_shadow(item)
    with pytest.raises(ValueError):
        controller.approve_canary(item, ShadowEvidence(2, 1.0, 0.0))


def test_canary_evidence_activates():
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    controller = DeploymentController(registry)
    controller.begin_shadow(item)
    controller.approve_canary(item, ShadowEvidence(20, 0.96, 0.0))
    controller.activate(item, CanaryEvidence(20, 0.0, 500.0))
    assert item.state == DeploymentState.ACTIVE


def test_controller_persists_shadow_and_canary_evidence(tmp_path):
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    store = DeploymentEvidenceStore(tmp_path / "hydra.db")
    controller = DeploymentController(registry, evidence_store=store)

    controller.begin_shadow(item)
    shadow = ShadowEvidence(20, 0.96, 0.0)
    controller.approve_canary(item, shadow)
    canary = CanaryEvidence(20, 0.0, 500.0)
    controller.activate(item, canary)

    variant_id = str(item.variant_id)
    assert store.latest_shadow(variant_id) == shadow
    assert store.latest_canary(variant_id) == canary


def _mirror(store, variant_id, n, *, agree=True, fail=False):
    for i in range(n):
        store.append(trace_id=f"t{i}", capability="reasoning.general", primary_variant_id="active",
                     primary_output="a", shadow_variant_id=variant_id,
                     shadow_output=None if fail else ("a" if agree else "b"), shadow_error=fail)


def test_promotion_uses_measured_traffic_since_the_phase_started(tmp_path):
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    traffic = RuntimeEvidenceStore(tmp_path / "runtime.jsonl")
    controller = DeploymentController(registry, runtime_evidence=traffic)
    vid = str(item.variant_id)
    _mirror(traffic, vid, 50)  # older traffic, before SHADOW began, does not count
    controller.begin_shadow(item)
    with pytest.raises(EvidenceRejected) as rejected:
        controller.approve_canary(item)
    assert rejected.value.evidence.samples == 0
    _mirror(traffic, vid, 19)
    _mirror(traffic, vid, 1, fail=True)
    with pytest.raises(EvidenceRejected):  # 1 error in 20 exceeds the 1% error budget
        controller.approve_canary(item)
    _mirror(traffic, vid, 80)
    evidence = controller.approve_canary(item)
    assert evidence.samples == 100 and evidence.error_rate == 0.01 and evidence.agreement_rate == 1.0
    assert item.state == DeploymentState.CANARY

    for i in range(25):
        traffic.append(trace_id=f"c{i}", capability="reasoning.general", primary_variant_id=vid,
                       primary_output="a", canary_variant_id=vid, canary_error=False, canary_latency_ms=6000.0)
    with pytest.raises(EvidenceRejected) as slow:  # p95 above the 5 s budget
        controller.activate(item)
    assert slow.value.evidence.p95_latency_ms == 6000.0


def test_shadow_disagreement_blocks_promotion(tmp_path):
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    traffic = RuntimeEvidenceStore(tmp_path / "runtime.jsonl")
    controller = DeploymentController(registry, runtime_evidence=traffic)
    controller.begin_shadow(item)
    _mirror(traffic, str(item.variant_id), 18)
    _mirror(traffic, str(item.variant_id), 2, agree=False)
    with pytest.raises(EvidenceRejected) as rejected:
        controller.approve_canary(item)
    assert rejected.value.evidence.agreement_rate == 0.9


def test_measuring_without_a_runtime_store_is_an_error():
    registry = DeploymentRegistry()
    item = deployment()
    registry.add(item)
    controller = DeploymentController(registry)
    controller.begin_shadow(item)
    with pytest.raises(ValueError, match="runtime evidence"):
        controller.approve_canary(item)
