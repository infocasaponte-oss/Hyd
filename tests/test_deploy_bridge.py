# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest
import httpx

from hydra.model_factory.deploy_bridge import register_request, variant_from_build
from hydra.model_factory.gguf import write_gguf
from hydra.runtime.benchmarking import BenchmarkResult
from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_controller import DeploymentController
from hydra.runtime.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.deployment_validation import DeploymentArtifactValidator
from hydra.runtime.model_factory import BuildState, ModelVariant
from hydra.runtime.promotion import PromotionDenied


def _build(models, status="CANDIDATE_REQUIRES_EVALUATION"):
    root = models / "hydra-pilot"
    root.mkdir(parents=True)
    gguf = root / "HYDRA.gguf"
    write_gguf(gguf, {"general.architecture": "qwen2", "qwen2.context_length": 4096,
                      "qwen2.embedding_length": 64, "qwen2.block_count": 2, "general.file_type": 15},
               {"token_embd.weight": [[0.1, 0.2], [0.3, 0.4]]})
    digest = hashlib.sha256(gguf.read_bytes()).hexdigest()
    (root / "build-manifest.json").write_text(json.dumps({
        "status": status, "approved": False, "artifact": str(gguf), "sha256": digest, "architecture": "qwen2",
        "inputs": {"base_sha256": "b" * 64, "dataset": {"files": {"train.jsonl": {"sha256": "d" * 64}}},
                   "recipe": {"base_model": "models/base/Qwen2.5-0.5B-Instruct"}, "trainer_sha256": "t" * 64},
        "stages": {"quantize": {str(gguf): digest}}}), encoding="utf-8")
    return root, digest


def _bench(variant_id: str, **overrides) -> BenchmarkResult:
    values = {"variant_id": variant_id, "profile": "rtx3060ti", "prompt_tokens": 512, "generated_tokens": 128,
              "ttft_ms": 420.0, "tokens_per_second": 61.0, "peak_vram_mb": 5200, "quality_score": 0.86,
              "passed": True}
    return BenchmarkResult(**{**values, **overrides})


def test_built_candidate_goes_through_promotion_and_the_deployment_plane(tmp_path):
    models = tmp_path / "models"
    build, digest = _build(models)
    assert variant_from_build(build, models).state == BuildState.QUANTIZED
    body = register_request(build, _bench(digest), ["coding"], models_root=models,
                            endpoint="http://127.0.0.1:11434/v1", served_model="hydra-local")
    variant = ModelVariant.model_validate(body["variant"])
    assert variant.state == BuildState.PROMOTED and variant.metadata["benchmark"]["peak_vram_mb"] == 5200
    assert variant.artifact_path == "hydra-pilot/HYDRA.gguf" and variant.lineage.base_model_sha256 == "b" * 64
    assert DeploymentArtifactValidator(models).validate(variant).architecture == "qwen2"  # admin register check

    registry = DeploymentRegistry()
    deployment = Deployment(variant=variant, capabilities={"coding"})
    registry.add(deployment)
    controller = DeploymentController(registry)
    assert deployment.state == DeploymentState.CANDIDATE  # never active without evidence
    controller.begin_shadow(deployment)
    controller.approve_canary(deployment, ShadowEvidence(samples=200, agreement_rate=0.97, error_rate=0.0))
    active = controller.activate(deployment, CanaryEvidence(requests=500, error_rate=0.0, p95_latency_ms=800))
    assert active.state == DeploymentState.ACTIVE


def test_candidate_over_the_vram_budget_is_not_promoted(tmp_path):
    models = tmp_path / "models"
    build, digest = _build(models)
    with pytest.raises(PromotionDenied):
        register_request(build, _bench(digest, peak_vram_mb=7900), ["coding"], models_root=models,
                         endpoint="http://127.0.0.1:11434/v1", served_model="hydra-local")
    with pytest.raises(ValueError, match="does not belong"):
        register_request(build, _bench("someone-else"), ["coding"], models_root=models,
                         endpoint="http://127.0.0.1:11434/v1", served_model="hydra-local")


def test_unfinished_or_misplaced_builds_are_refused(tmp_path):
    models = tmp_path / "models"
    with pytest.raises(ValueError, match="not a finished candidate"):
        variant_from_build(_build(models, status="FAILED")[0], models)
    elsewhere, _ = _build(tmp_path / "other")
    with pytest.raises(ValueError, match="outside the deployment models root"):
        variant_from_build(elsewhere, models)


async def test_registered_candidate_routes_inference_to_its_served_model(tmp_path):
    from hydra.runtime.physical_inference import PhysicalInferenceClient

    models = tmp_path / "models"
    build, digest = _build(models)
    body = register_request(build, _bench(digest), ["coding"], models_root=models,
                            endpoint="http://127.0.0.1:11434/v1", served_model="hydra-local")
    variant = ModelVariant.model_validate(body["variant"])
    registry = DeploymentRegistry()
    registry.add(Deployment(variant=variant, capabilities={"coding"}))

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        assert json.loads(request.content)["model"] == "hydra-local"
        return httpx.Response(200, json={"choices": [{"message": {"content": "candidate response"}}]})

    client = PhysicalInferenceClient(registry, transport=httpx.MockTransport(respond))
    assert await client.generate(str(variant.variant_id), "test", 32) == "candidate response"


@pytest.mark.parametrize("endpoint", ["https://example.com/v1", "http://user:pass@localhost/v1",
                                      "http://localhost/v1?token=secret"])
def test_bridge_rejects_invalid_inference_endpoint(tmp_path, endpoint):
    with pytest.raises(ValueError, match="local HTTP"):
        register_request(tmp_path, _bench("unused"), ["coding"], endpoint=endpoint, served_model="hydra-local")
