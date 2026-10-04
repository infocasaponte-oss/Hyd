# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.runtime import api


def test_health_is_liveness_only():
    with TestClient(api.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["hydra"] == "ok"
    assert "llm" not in response.json()


def test_ready_returns_503_when_llm_is_unhealthy(monkeypatch):
    async def unhealthy() -> bool:
        return False

    monkeypatch.setattr(api.llm, "health", unhealthy)

    with TestClient(api.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert "llm_unhealthy" in body["reasons"]
