# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Characterize legacy handlers both standalone and mounted in the gateway."""
import pytest
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hydra.api.runtime_routes import register_runtime_routes
from hydra.runtime import api
from hydra.runtime.contracts import HydraResult, TaskStatus
from hydra.runtime.rate_limit import SlidingWindowRateLimiter
from hydra.runtime.security import SecurityConfig
from hydra.core.durable_events import JsonlEventStore
from hydra.runtime.kernel import HydraKernel


@pytest.fixture(params=["standalone", "mounted"])
def legacy_client(request, monkeypatch):
    monkeypatch.setattr(api, "security_config", SecurityConfig(api_token="api-test", admin_token=None))
    monkeypatch.setattr(api, "rate_limiter", SlidingWindowRateLimiter())
    app = api.app
    if request.param == "mounted":
        app = FastAPI()
        register_runtime_routes(app)
    # Exercise HTTP handlers without starting a worker or making model calls.
    return TestClient(app, headers={"Authorization": "Bearer api-test"})


@pytest.mark.parametrize("path,payload", [
    ("/v1/chat", {"message": "hello"}),
    ("/hydra/v1/tasks/route", {"goal": "hello"}),
    ("/hydra/v1/tasks/execute", {"goal": "hello"}),
])
def test_wrong_token_is_rejected_before_execution(legacy_client, path, payload):
    response = legacy_client.post(path, json=payload, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_chat_retains_legacy_answer_envelope_and_model_arguments(legacy_client, monkeypatch):
    calls = []

    async def chat(messages, *, max_tokens):
        calls.append((messages, max_tokens))
        return "legacy answer"

    monkeypatch.setattr(api.llm, "chat", chat)
    response = legacy_client.post("/v1/chat", json={"message": "hello", "max_tokens": 128})
    assert response.status_code == 200
    assert response.json() == {"answer": "legacy answer"}
    assert calls == [([{"role": "user", "content": "hello"}], 128)]


def test_chat_provider_failure_retains_safe_502(legacy_client, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("private provider diagnostics")

    monkeypatch.setattr(api.llm, "chat", broken)
    response = legacy_client.post("/v1/chat", json={"message": "hello"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Local model unavailable"}


def test_execute_serializes_the_legacy_result(legacy_client, monkeypatch):
    async def run(task, llm):
        assert task.goal == "hello"
        return HydraResult(task_id=task.id, status=TaskStatus.COMPLETED,
                           answer="done", confidence=0.7, trace_id="trace", metadata={"verified": False})

    monkeypatch.setattr(api.kernel, "run", run)
    task_id = "00000000-0000-0000-0000-000000000001"
    response = legacy_client.post("/hydra/v1/tasks/execute", json={"id": task_id, "goal": "hello"})
    assert response.status_code == 200
    assert response.json() == {"task_id": task_id, "status": "completed", "answer": "done",
                               "confidence": 0.7, "trace_id": "trace", "metadata": {"verified": False}}


def test_coding_remains_admin_only_even_with_api_token(legacy_client):
    response = legacy_client.post("/hydra/v1/coding/verify-fix", json={"goal": "fix", "repository": "."})
    assert response.status_code == 503


def test_legacy_chat_does_not_accept_openai_messages_schema(legacy_client):
    response = legacy_client.post("/v1/chat", json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 422


def test_route_persists_original_audit_events(legacy_client, monkeypatch, tmp_path):
    events = JsonlEventStore(tmp_path / "events.jsonl")
    monkeypatch.setattr(api, "kernel", HydraKernel(events=events))
    task_id = "00000000-0000-0000-0000-000000000001"
    response = legacy_client.post("/hydra/v1/tasks/route", json={"id": task_id, "goal": "Debug Python"})
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "routing"
    assert body["route"] == {"task_type": "coding", "capability": "coding.general",
                              "needs_verification": True, "needs_tools": True,
                              "parallelism": 1, "confidence": 0.75}
    recorded = JsonlEventStore(events.path).for_aggregate(UUID(task_id))
    assert [event.event_type for event in recorded] == [
        "hydra.task.created", "hydra.task.transitioned", "hydra.route.completed",
    ]
    assert all(event.trace_id == body["trace_id"] for event in recorded)
    assert events.verify_integrity().valid
