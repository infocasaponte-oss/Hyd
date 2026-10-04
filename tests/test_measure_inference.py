# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import httpx
import pytest

from hydra.training import measure_inference as module


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_stream_completion_is_required(tmp_path, monkeypatch, complete):
    monkeypatch.setattr(module, "candidate_hash", lambda _: "weights")

    async def identity(*args):
        return {"artifact_sha256": "weights"}

    monkeypatch.setattr(module, "model_identity", identity)
    chunks = [{"message": {"content": "def solve(xs): return sum(xs)"}}]
    if complete:
        chunks.append({"done": True, "eval_count": 10, "eval_duration": 100_000_000})
    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, content="\n".join(json.dumps(c) for c in chunks)))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(**kw, transport=transport))
    output = tmp_path / "metrics.json"
    if complete:
        result = await module.measure("hydra", tmp_path / "manifest.json", output, 2)
        assert result["status"] == "MEASURED_DIAGNOSTIC"
        assert result["repeated_median_tokens_per_second"] == 100
        assert result["peak_vram_mb"] is None
        assert result["approved"] is False
    else:
        with pytest.raises(ValueError, match="incomplete stream"):
            await module.measure("hydra", tmp_path / "manifest.json", output, 2)
        assert json.loads(output.read_text())["status"] == "FAILED"
