# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import httpx
import pytest

from hydra.training import validate_kev as module
from hydra.providers.decision import LocalSystemOneProvider


@pytest.mark.parametrize("device,pin,status", [
    ("cpu", module.PIN, "NOT_VALIDATED"),
    ("cuda", "different", "NOT_VALIDATED"),
    ("cuda", module.PIN, "INFERENCE_COMPLETED"),
])
async def test_live_probe_requires_identity_and_gpu(tmp_path, monkeypatch, device, pin, status):
    calls = []

    def respond(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"name": "kev-latest", "run": pin, "device": device}]})
        calls.append(request)
        body = json.loads(request.content)
        choice = dict(module.CASES)[body["state"]]
        return httpx.Response(200, json={"model": "kev-latest", "answers": {"topic": {
            "type": "choice", "choice": choice, "confidence": 1,
            "probabilities": {k: float(k == choice) for k in body["questions"]["topic"]["criteria"]}}}})

    provider = LocalSystemOneProvider(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(module, "LocalSystemOneProvider", lambda **kw: provider)
    result = await module.validate(tmp_path / "result.json")
    assert result["status"] == status and result["approved"] is False
    assert len(calls) == (3 if status == "INFERENCE_COMPLETED" else 0)
    assert provider.client.is_closed
