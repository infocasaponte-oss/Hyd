# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest
from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.core.config import Settings
from hydra.tools.sandbox import SubprocessSandbox


@pytest.fixture
def client(tmp_path):
    settings = Settings(offline=True, sandbox_backend="subprocess", workspace_dir=tmp_path / "ws",
                        data_dir=tmp_path / "data", api_key="secret")
    with TestClient(create_app(settings, sandbox=SubprocessSandbox())) as c:
        c.headers["X-API-Key"] = "secret"
        yield c


def test_health_is_public(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json()["offline"] is True


def test_auth_required(client):
    r = client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "hola"}]},
                    headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_run_and_inspect_task(client):
    r = client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "¿Cuánto es 6 × 7?"}]})
    assert r.status_code == 200
    body = r.json()
    assert "42" in body["answer"]
    tid = body["meta"]["task_id"]
    assert client.get(f"/v1/tasks/{tid}").json()["status"] == "completed"
    events = client.get(f"/v1/tasks/{tid}/events").json()
    types = [e["type"] for e in events]
    assert types[0] == "task.created" and "task.completed" in types and "counterfactual.analyzed" in types
    assert client.get(f"/v1/tasks/{tid}/replay").json()["final_answer"] == body["answer"]
    assert client.post(f"/v1/tasks/{tid}/feedback", json={"score": 1.0}).json()["updated_runs"] >= 1
    assert client.get("/v1/tasks/00000000-0000-0000-0000-000000000000").status_code == 404


def test_stream_emits_events_and_result(client):
    with client.stream("POST", "/v1/hydra/stream",
                       json={"messages": [{"role": "user", "content": "¿Cuánto es 2+2?"}]}) as r:
        text = "".join(r.iter_text())
    assert "event: task.created" in text and "event: result" in text and "2+2 = 4" in text


def test_openai_compatible_facade(client):
    r = client.post("/v1/chat/completions",
                    json={"model": "hydra-fast", "messages": [{"role": "user", "content": "¿Cuánto es 9*9?"}]})
    assert r.status_code == 200 and "81" in r.json()["choices"][0]["message"]["content"]
    assert client.post("/v1/chat/completions", json={"model": "gpt", "messages": []}).status_code == 400


def test_os_endpoints(client):
    body = client.post("/v1/hydra", json={"messages": [{"role": "user", "content": CODE}]}).json()
    tid = body["meta"]["task_id"]
    assert client.get(f"/v1/tasks/{tid}/provenance").json()
    assert {a["type"] for a in client.get(f"/v1/tasks/{tid}/artifacts").json()} >= {"answer", "execution_plan"}
    assert client.get(f"/v1/tasks/{tid}/claims").json()["counterfactual"] is not None
    status = client.get("/v1/os/status").json()
    assert {"config", "semantic_cache", "failure_memory", "counterfactual", "learned_router"} <= set(status)
    cls = client.post("/v1/policy/classify", json={"text": "password: hunter2secret"}).json()
    assert cls["sensitivity"] == "secret" and "hunter2secret" not in cls["redacted"]
    assert "git.apply_patch" in client.get("/v1/policy").json()["confirm_tools"]
    ev = client.post("/v1/evals/run", json={"model_id": "fast-local", "suites": ["reasoning"]}).json()
    assert ev["suites"]["reasoning"]["total"] == 4


def test_lab_and_factory_endpoints(client):
    exp = client.post("/v1/lab/experiments", json={"name": "t", "overrides": {"accept_confidence": 0.8}}).json()
    assert exp["status"] == "draft"
    assert client.post("/v1/lab/experiments", json={"name": "bad", "overrides": {"nope": 1}}).status_code == 400
    assert client.post(f"/v1/lab/experiments/{exp['id']}/shadow").json()["status"] == "shadow"
    assert any(e["id"] == exp["id"] for e in client.get("/v1/lab/experiments").json())
    assert "toolchain" in client.get("/v1/factory/status").json()
    assert client.get("/v1/factory/hardware").json()["system_ram_gb"] > 0
    job = client.post("/v1/factory/jobs", json={"kind": "jit"})
    assert job.status_code == 202 and job.json()["status"] == "queued"  # enqueued, never run in the API
    assert client.get(f"/v1/factory/jobs/{job.json()['id']}").json()["status"] == "queued"
    assert client.post("/v1/factory/jobs", json={"kind": "rm -rf"}).status_code == 400
    assert client.get("/v1/factory/resolve/unknown").status_code == 404


CODE = "Revisa:\n```python\ndef f(x):\n    return x + 1\nprint(f(1))\n```"


def test_models_tools_memory_endpoints(client):
    assert len(client.get("/v1/models").json()) >= 5
    assert "python.execute" in {t["name"] for t in client.get("/v1/tools").json()}
    client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "HydraAPI depends on Redis"}]})
    g = client.get("/v1/memory/graph", params={"node": "Redis", "predicate": "depends_on"}).json()
    assert g["dependents"] == ["HydraAPI"]
    assert client.get("/v1/memory/search", params={"q": "Redis"}).json()


def test_api_rate_limit_is_enforced(tmp_path):
    settings = Settings(
        offline=True,
        sandbox_backend="subprocess",
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        api_key="secret",
        api_rate_limit_per_minute=1,
    )
    with TestClient(create_app(settings, sandbox=SubprocessSandbox())) as c:
        headers = {"X-API-Key": "secret"}
        assert c.get("/v1/models", headers=headers).status_code == 200
        limited = c.get("/v1/models", headers=headers)
        assert limited.status_code == 429
        assert limited.json()["detail"] == "HYDRA rate limit exceeded"


def test_unconfigured_api_rejects_remote_clients(tmp_path):
    settings = Settings(
        offline=True,
        sandbox_backend="subprocess",
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        api_key="",
    )
    with TestClient(
        create_app(settings, sandbox=SubprocessSandbox()),
        client=("10.0.0.2", 50000),
    ) as c:
        response = c.get("/v1/models")
        assert response.status_code == 503
        assert response.json()["detail"] == "API key is not configured for remote access"
