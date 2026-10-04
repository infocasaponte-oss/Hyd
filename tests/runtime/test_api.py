# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.runtime.api import app

client = TestClient(app)


def test_models_endpoint_is_local_inventory():
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert "models" in response.json()


def test_chat_budget_rejects_large_request():
    response = client.post("/v1/chat", json={"message": "x" * 50001})
    assert response.status_code == 413
