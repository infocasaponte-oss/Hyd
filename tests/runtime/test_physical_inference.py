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


def deployment(endpoint: str) -> Deployment:
    variant = ModelVariant(
        lineage=ModelLineage(
            base_model="base",
            base_model_sha256="a" * 64,
        ),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
        metadata={"endpoint": endpoint, "served_model": "local-model"},
    )
    return Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=DeploymentState.ACTIVE,
        generation=1,
    )


@pytest.mark.asyncio
async def test_physical_client_calls_local_openai_compatible_endpoint():
    registry = DeploymentRegistry()
    item = deployment("http://127.0.0.1:8081/v1")
    registry.add(item)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "local-model"
        assert payload["messages"][0]["content"] == "hello"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "physical"}}]},
        )

    client = PhysicalInferenceClient(
        registry,
        transport=httpx.MockTransport(handler),
    )
    answer = await client.generate(str(item.variant_id), "hello", 64)
    assert answer == "physical"


def test_physical_client_rejects_remote_endpoint():
    registry = DeploymentRegistry()
    item = deployment("http://example.com/v1")
    registry.add(item)
    client = PhysicalInferenceClient(registry)

    with pytest.raises(PhysicalInferenceUnavailable, match="local HTTP"):
        client._endpoint(item)
