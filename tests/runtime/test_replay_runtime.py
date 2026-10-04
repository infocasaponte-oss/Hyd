# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.replay_runtime import runtime_replay_manifest


def test_runtime_manifest_names_physical_variant():
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )
    deployment = Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=DeploymentState.ACTIVE,
        generation=4,
    )
    manifest = runtime_replay_manifest(
        task_id=uuid4(),
        trace_id="trace",
        hydra_version="0.3.1.dev0",
        deployment=deployment,
        event_types=["hydra.model.selected"],
    )
    assert manifest.selected_variant_id == str(variant.variant_id)
    assert manifest.selected_variant_sha256 == "b" * 64
    assert manifest.deployment_generation == 4
