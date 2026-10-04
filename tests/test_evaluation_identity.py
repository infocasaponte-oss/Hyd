# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import httpx
import pytest

from hydra.training.evaluate_corpus import candidate_hash, evaluate, model_identity
from hydra.training.verified_corpus import sha256
from hydra.training.verified_corpus import build as build_corpus
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_identity_rejects_a_different_served_gguf():
    def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "hydra:latest", "digest": "manifest"}]})
        return httpx.Response(200, json={"modelfile": 'FROM "C:\\models\\sha256-' + "a" * 64 + '"\n'})
    async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(respond)) as client:
        identity = await model_identity(client, "hydra", "a" * 64)
        assert identity["artifact_sha256"] == "a" * 64
        with pytest.raises(ValueError, match="served GGUF"):
            await model_identity(client, "hydra", "b" * 64)


def test_candidate_rejects_modified_weights(tmp_path):
    artifact = tmp_path / "HYDRA.gguf"
    artifact.write_bytes(b"original")
    manifest = tmp_path / "build-manifest.json"
    manifest.write_text(json.dumps({"status": "CANDIDATE_REQUIRES_EVALUATION",
                                   "artifact": str(artifact), "sha256": sha256(artifact)}))
    assert candidate_hash(manifest) == sha256(artifact)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        candidate_hash(manifest)


@pytest.mark.asyncio
async def test_negative_subset_is_rejected_before_io(tmp_path):
    with pytest.raises(ValueError, match="nonnegative"):
        await evaluate("hydra", tmp_path, tmp_path / "result.json", -1)


@pytest.mark.asyncio
async def test_model_change_invalidates_saved_report(tmp_path, monkeypatch):
    from hydra.training import evaluate_corpus as module
    build_corpus(tmp_path / "corpus", per_family=1)
    calls = 0

    def respond(request):
        nonlocal calls
        if request.url.path == "/api/tags":
            calls += 1
            return httpx.Response(200, json={"models": [{"name": "hydra:latest", "digest": str(calls)}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"modelfile": "FROM /blobs/sha256-" + "a" * 64})
        return httpx.Response(200, json={"message": {"content": "def solve(xs): return xs.count(2)"},
                                        "eval_count": 10, "eval_duration": 1_000_000_000})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))

    async def execute(*args, **kwargs):
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(module.DockerSandbox, "execute_python", execute)
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match="changed during"):
        await evaluate("hydra", tmp_path / "corpus", output, limit=1)
    report = json.loads(output.read_text())
    assert report["status"] == "INVALID_MODEL_IDENTITY"
    assert report["approved"] is False
    assert report["cases"][0]["generation_tokens_per_second"] == 10
