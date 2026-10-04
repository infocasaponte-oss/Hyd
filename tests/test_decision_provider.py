# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import httpx
import pytest

from hydra.providers.decision import LocalSystemOneProvider, validate_answers

QUESTIONS = {"route": {"type": "choice", "criteria": {"chat": None, "code": None}}}


@pytest.mark.asyncio
async def test_local_contract():
    def respond(request):
        assert request.url.path == "/v1/systemone"
        assert json.loads(request.content)["questions"] == QUESTIONS
        return httpx.Response(200, json={"model": "kev-latest", "answers": {"route": {
            "type": "choice", "choice": "chat", "probabilities": {"chat": 0.8, "code": 0.2},
            "confidence": 0.6}}})
    provider = LocalSystemOneProvider(transport=httpx.MockTransport(respond))
    try:
        assert (await provider.decide("hola", QUESTIONS))["answers"]["route"]["choice"] == "chat"
    finally:
        await provider.close()


@pytest.mark.parametrize("probs", [{"chat": 0.8, "code": 0.8}, {"unknown": 1},
                                    {"chat": float("nan"), "code": 0.2}])
def test_invalid_distribution_rejected(probs):
    with pytest.raises(ValueError):
        validate_answers(QUESTIONS, {"answers": {"route": {
            "type": "choice", "choice": "chat", "probabilities": probs, "confidence": 0.6}}})


def test_remote_endpoint_rejected():
    with pytest.raises(ValueError):
        LocalSystemOneProvider("https://example.com")


def test_noul_and_score_contracts():
    questions = {"yes": {"type": "noul"}, "level": {"type": "score", "criteria": ["low", "high"]}}
    payload = {"answers": {"yes": {"type": "noul", "noul": 0.7}, "level": {
        "type": "score", "score": 0.75, "probabilities": {"0": 0.25, "1": 0.75}, "confidence": 0.5}}}
    assert validate_answers(questions, payload) == payload
    payload["answers"]["level"]["score"] = 1
    with pytest.raises(ValueError, match="distribution"):
        validate_answers(questions, payload)


@pytest.mark.asyncio
async def test_timeout_does_not_produce_decision():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    provider = LocalSystemOneProvider(transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(httpx.ReadTimeout):
            await provider.decide("hola", QUESTIONS)
    finally:
        await provider.close()
