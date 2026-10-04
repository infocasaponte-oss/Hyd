# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.deployment_resolver import DeploymentResolver
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant


def promoted(quant: str) -> ModelVariant:
    return ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization=quant,
        artifact_path=f"{quant}.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )


def deploy(quant: str, generation: int) -> Deployment:
    item = Deployment(
        variant=promoted(quant),
        capabilities={"reasoning.general"},
        generation=generation,
    )
    item.transition(DeploymentState.SHADOW)
    item.transition(DeploymentState.CANARY)
    return item


def test_candidate_cannot_skip_to_active():
    item = Deployment(variant=promoted("Q4_K_M"), capabilities={"reasoning.general"})
    with pytest.raises(ValueError):
        item.transition(DeploymentState.ACTIVE)


def test_activate_preserves_previous_for_rollback():
    registry = DeploymentRegistry()
    old = deploy("Q4_K_M", 1)
    registry.add(old)
    registry.activate(str(old.variant_id))
    new = deploy("Q5_K_M", 2)
    registry.add(new)
    registry.activate(str(new.variant_id))
    assert old.state == DeploymentState.DEPRECATED
    assert DeploymentResolver(registry).resolve("reasoning.general") is new
    restored = registry.rollback("reasoning.general")
    assert restored is old
    assert old.state == DeploymentState.ACTIVE


def test_partial_capability_rollout_does_not_orphan_other_capabilities():
    registry = DeploymentRegistry()

    old = Deployment(
        variant=promoted("Q4_K_M"),
        capabilities={"reasoning.general", "coding.python"},
        generation=1,
    )
    old.transition(DeploymentState.SHADOW)
    old.transition(DeploymentState.CANARY)
    registry.add(old)
    registry.activate(str(old.variant_id))

    new = Deployment(
        variant=promoted("Q5_K_M"),
        capabilities={"reasoning.general"},
        generation=2,
    )
    new.transition(DeploymentState.SHADOW)
    new.transition(DeploymentState.CANARY)
    registry.add(new)
    registry.activate(str(new.variant_id))

    assert registry.active_for("reasoning.general") is new
    assert registry.active_for("coding.python") is old
    assert old.state == DeploymentState.ACTIVE
    assert old.metadata["active_capabilities"] == ["coding.python"]


def test_partial_capability_rollback_restores_only_requested_binding():
    registry = DeploymentRegistry()

    old = Deployment(
        variant=promoted("Q4_K_M"),
        capabilities={"reasoning.general", "coding.python"},
        generation=1,
    )
    old.transition(DeploymentState.SHADOW)
    old.transition(DeploymentState.CANARY)
    registry.add(old)
    registry.activate(str(old.variant_id))

    new = Deployment(
        variant=promoted("Q5_K_M"),
        capabilities={"reasoning.general"},
        generation=2,
    )
    new.transition(DeploymentState.SHADOW)
    new.transition(DeploymentState.CANARY)
    registry.add(new)
    registry.activate(str(new.variant_id))

    restored = registry.rollback("reasoning.general")

    assert restored is old
    assert registry.active_for("reasoning.general") is old
    assert registry.active_for("coding.python") is old
    assert new.state == DeploymentState.DEPRECATED
    assert sorted(old.metadata["active_capabilities"]) == [
        "coding.python",
        "reasoning.general",
    ]
