# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import httpx
import pytest

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant
from hydra.runtime.physical_inference import (
    PhysicalInferenceClient,
    PhysicalInferenceUnavailable,
)


@pytest.mark.asyncio
async def test_physical_http_failure_is_normalized_for_fallback():
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
        metadata={"endpoint": "http://127.0.0.1:8081/v1"},
    )
    deployment = Deployment(
        variant=variant,
        capabilities={"chat.multilingual"},
        state=DeploymentState.ACTIVE,
        generation=1,
    )
    registry = DeploymentRegistry()
    registry.add(deployment)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = PhysicalInferenceClient(
        registry,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PhysicalInferenceUnavailable, match="unavailable"):
        await client.generate(str(variant.variant_id), "hello", 32)
