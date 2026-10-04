# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""One gateway serves the platform and the HYDRA-SO runtime line (docs/INTEGRATION_PLAN.md, phase 5)."""
from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.runtime import api as runtime_api


def _paths(app) -> set[tuple[str, str]]:
    return {(route.path, method) for route in app.routes for method in getattr(route, "methods", ())}


def test_runtime_routes_are_mounted_without_shadowing_platform_routes(settings):
    app = create_app(settings)
    paths = _paths(app)
    for expected in [("/ready", "GET"), ("/v1/chat", "POST"), ("/hydra/v1/tasks/route", "POST"),
                     ("/hydra/v1/tasks/execute", "POST"), ("/hydra/v1/admin/metrics", "GET"),
                     ("/hydra/v1/admin/deployments/register", "POST"), ("/hydra/v1/coding/verify-fix", "POST"),
                     ("/hydra/v1/admin/outbox/dead-letters", "GET"), ("/hydra/v1/models/artifacts", "GET")]:
        assert expected in paths, expected
    # collisions resolved in favour of the platform: exactly one route per (path, method)
    for path, method in [("/health", "GET"), ("/v1/models", "GET"), ("/v1/translate", "POST")]:
        routes = [r for r in app.routes if getattr(r, "path", None) == path and method in getattr(r, "methods", ())]
        assert len(routes) == 1 and not routes[0].name.startswith("runtime."), path
    glossary_puts = [r for r in app.routes if "PUT" in getattr(r, "methods", ())
                     and getattr(r, "path", "").startswith("/v1/glossaries/")]
    assert len(glossary_puts) == 1


def test_runtime_line_disabled_by_setting(settings):
    app = create_app(settings.model_copy(update={"runtime_api": False}))
    assert ("/ready", "GET") not in _paths(app)


def test_unified_gateway_serves_both_lines(settings):
    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()
        assert health["status"] == "ok" and health["hydra"] == "ok"
        routed = client.post("/hydra/v1/tasks/route", json={"goal": "Debug this Python test failure"})
        assert routed.status_code == 200 and routed.json()["route"]["task_type"] == "coding"
        ready = client.get("/ready")
        assert ready.status_code in (200, 503) and "worker_running" in ready.json()
        assert ready.json()["worker_running"] is True  # outbox worker runs inside the gateway lifespan
        assert client.get("/hydra/v1/models/artifacts").json()["count"] >= 0
        models = client.get("/v1/models")
        assert models.status_code == 200
        model_ids = {item["id"] for item in models.json()}
        assert model_ids == {"hydra", "hydra-fast", "hydra-deep", "hydra-max", "hydra-private"}
        assert "qwen2.5-coder-7b" not in model_ids  # physical backend stays internal
        assert all(isinstance(item["available"], bool) for item in models.json())
        catalog = client.get("/hydra/v1/models/catalog").json()  # Studio's internal backend table
        assert catalog and all({"provider", "tier", "capabilities", "provider_healthy", "installed"} <= set(m) for m in catalog)
        # admin routes fail closed without HYDRA_ADMIN_TOKEN
        assert client.get("/hydra/v1/admin/metrics").status_code == 503
        metrics = client.get("/metrics").text
        for gauge in ("hydra_capture_outbox_pending", "hydra_capture_outbox_dead_letters",
                      "hydra_runtime_outbox_pending", "hydra_runtime_outbox_dead_letters"):
            assert gauge in metrics, gauge


def test_one_token_protects_both_lines(settings):
    previous = runtime_api.security_config
    with TestClient(create_app(settings.model_copy(update={"api_key": "s3cret"}))) as client:
        assert client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "hola"}]}).status_code == 401
        assert client.post("/v1/chat", json={"message": "hola"}).status_code == 401
        for header in ({"Authorization": "Bearer s3cret"}, {"X-API-Key": "s3cret"}, {"X-Hydra-Token": "s3cret"}):
            ok = client.post("/v1/hydra", json={"messages": [{"role": "user", "content": "¿Cuánto es 2+2?"}]},
                             headers=header)
            assert ok.status_code == 200, header
            # the runtime line accepts the same token; 502 = no local llama-server in tests, not an auth error
            assert client.post("/v1/chat", json={"message": "hola"}, headers=header).status_code in (200, 502)
    assert runtime_api.security_config is previous  # restored when the app stops


def test_task_routing_requires_gateway_auth_before_writing_events(settings, monkeypatch):
    from unittest.mock import Mock

    prepare = Mock(wraps=runtime_api.kernel.prepare)
    monkeypatch.setattr(runtime_api.kernel, "prepare", prepare)
    with TestClient(create_app(settings.model_copy(update={"api_key": "route-secret"}))) as client:
        response = client.post("/hydra/v1/tasks/route", json={"goal": "Debug Python"})
        assert response.status_code == 401
        prepare.assert_not_called()
        response = client.post("/hydra/v1/tasks/route", json={"goal": "Debug Python"},
                               headers={"Authorization": "Bearer route-secret"})
        assert response.status_code == 200
        prepare.assert_called_once()


def test_platform_uses_hardened_runtime_sandbox_by_default(monkeypatch):
    from hydra.core.config import Settings
    from hydra.runtime.sandbox import DEFAULT_SANDBOX_IMAGE
    from hydra.tools.sandbox import DockerSandbox

    monkeypatch.delenv("HYDRA_SANDBOX_IMAGE", raising=False)
    assert Settings(_env_file=None).sandbox_image == DEFAULT_SANDBOX_IMAGE
    assert DockerSandbox().image == DEFAULT_SANDBOX_IMAGE
