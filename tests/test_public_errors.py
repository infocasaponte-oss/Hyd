# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Task failures reach API clients as a public message; internal detail stays in logs/events
(CodeQL py/stack-trace-exposure)."""
from uuid import uuid4

from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.core.kernel import HydraTaskFailed

INTERNAL = "ConnectError: http://10.0.0.5:8000/v1 refused while loading C:\\srv\\hydra\\secrets\\key.pem"


def test_public_message_hides_internal_detail():
    exc = HydraTaskFailed(uuid4(), INTERNAL, "unavailable")
    assert "10.0.0.5" not in exc.public_message() and "key.pem" not in exc.public_message()
    assert str(exc.task_id) in exc.public_message()
    assert "task failed" in HydraTaskFailed(uuid4(), INTERNAL, "something-new").public_message()


def test_api_returns_public_task_failures(settings):
    task_id = uuid4()

    async def failing(*args, **kwargs):
        raise HydraTaskFailed(task_id, INTERNAL, "unavailable")

    with TestClient(create_app(settings)) as client:
        client.app.state.runtime.lab.serve = failing
        response = client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "hola"}]})
        assert response.status_code == 503
        body = response.json()
        assert body["kind"] == "unavailable" and body["task_id"] == str(task_id)
        assert "10.0.0.5" not in response.text and "key.pem" not in response.text
        chat = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hola"}]})
        assert chat.status_code == 502 and "10.0.0.5" not in chat.text
