# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.runtime_health import RuntimeHealth
from hydra.runtime.traffic_router import TrafficRouter


def item(state: DeploymentState, generation: int) -> Deployment:
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path=f"{generation}.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )
    return Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=state,
        generation=generation,
    )


def test_routes_active_and_shadow():
    registry = DeploymentRegistry()
    active = item(DeploymentState.ACTIVE, 1)
    shadow = item(DeploymentState.SHADOW, 2)
    registry.add(active)
    registry.add(shadow)
    decision = TrafficRouter(registry, RuntimeHealth()).route(
        "reasoning.general", "trace-1"
    )
    assert decision.primary is active
    assert decision.shadow is shadow


def test_unhealthy_active_falls_back_to_deprecated():
    registry = DeploymentRegistry()
    old = item(DeploymentState.DEPRECATED, 1)
    active = item(DeploymentState.ACTIVE, 2)
    registry.add(old)
    registry.add(active)
    health = RuntimeHealth()
    for _ in range(3):
        health.failure(str(active.variant_id))
    decision = TrafficRouter(registry, health).route(
        "reasoning.general", "trace-2"
    )
    assert decision.primary is old
