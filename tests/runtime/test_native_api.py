# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.runtime.api import app

client = TestClient(app)


def test_native_task_route():
    response = client.post(
        "/hydra/v1/tasks/route",
        json={"goal": "Debug this Python test failure"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "routing"
    assert body["route"]["task_type"] == "coding"
    assert body["route"]["needs_verification"] is True
