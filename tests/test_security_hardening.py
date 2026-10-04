# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Regression tests for the 2026-10-01 audit fixes (docs/AUDITORIA_INTEGRAL_REPO_2026-10-01.md)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hydra.api.main import create_app
from hydra.api.security import is_loopback
from hydra.core.atomic import write_text_atomic
from hydra.edge.sync import SyncBundle, SyncCursor
from hydra.governance.config_registry import ConfigRegistry
from hydra.core.paths import PathNotAllowed
from hydra.ledger.signing import Signer
from hydra.observability.tracing import BUCKETS_PCT, CognitiveTracer
from hydra.runtime.model_scout import HashCache, scan_models

REMOTE = ("203.0.113.7", 50000)


def _ws_kinds(ws) -> list[str]:
    ws.send_json({"goal": "¿Cuánto es 2+2?"})
    kinds = []
    while True:
        msg = ws.receive_json()
        kinds.append(msg["type"])
        if msg["type"] in ("result", "error"):
            return kinds


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
                                           ("127.0.0.2", True), ("testclient", True), ("10.0.0.1", False),
                                           ("203.0.113.7", False), ("example.org", False)])
def test_loopback_detection(host, expected):
    assert is_loopback(host) is expected


def test_websocket_without_key_rejects_remote_clients(settings):
    with TestClient(create_app(settings), client=REMOTE) as client:
        with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/v1/ws/tasks") as ws:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_requires_the_key_and_never_reads_it_from_the_query(settings):
    app = create_app(settings.model_copy(update={"api_key": "s3cret"}))
    with TestClient(app, client=REMOTE) as client:
        for path, headers in [("/v1/ws/tasks", {}), ("/v1/ws/tasks?api_key=s3cret", {}),
                              ("/v1/ws/tasks", {"x-api-key": "wrong"})]:
            with pytest.raises(WebSocketDisconnect), client.websocket_connect(path, headers=headers) as ws:
                ws.receive_json()
        with client.websocket_connect("/v1/ws/tasks", headers={"x-api-key": "s3cret"}) as ws:
            assert _ws_kinds(ws)[-1] == "result"
        # Browsers cannot set headers on WebSockets: the token may travel as a subprotocol.
        with client.websocket_connect("/v1/ws/tasks", subprotocols=["hydra.v1", "hydra.token.s3cret"]) as ws:
            assert _ws_kinds(ws)[-1] == "result"


def test_sync_import_never_trusts_client_supplied_keys(settings):
    with TestClient(create_app(settings)) as client:
        attacker = Signer.generate()
        bundle = SyncBundle(origin="evil", cursor_from=SyncCursor(), cursor_to=SyncCursor(world_version=1))
        bundle.signature = attacker.envelope(bundle.digest())
        body = {"bundle": bundle.model_dump(mode="json")}
        # The old body field is rejected outright...
        assert client.post("/hydra/v1/edge/sync/import",
                           json={**body, "trusted_keys": [attacker.public_pem]}).status_code == 422
        # ...and a bundle signed by an unknown key is refused.
        report = client.post("/hydra/v1/edge/sync/import", json=body).json()
        assert report["ok"] is False and "untrusted" in report["reason"]


def test_sync_import_accepts_operator_installed_keys(settings):
    trusted = settings.data_dir / "keys" / "trusted"
    trusted.mkdir(parents=True)
    partner = Signer.generate()
    (trusted / "partner.pub.pem").write_text(partner.public_pem, encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        bundle = SyncBundle(origin="partner", cursor_from=SyncCursor(), cursor_to=SyncCursor())
        bundle.signature = partner.envelope(bundle.digest())
        report = client.post("/hydra/v1/edge/sync/import", json={"bundle": bundle.model_dump(mode="json")}).json()
        assert report["ok"] is True


def test_admin_routes_need_the_admin_token(settings):
    app = create_app(settings.model_copy(update={"api_key": "k", "admin_token": "adm"}))
    with TestClient(app, client=REMOTE) as client:
        key = {"x-api-key": "k"}
        assert client.post("/hydra/v1/flags/new_critic", json={"value": "on"}, headers=key).status_code == 403
        ok = client.post("/hydra/v1/flags/new_critic", json={"value": "on"},
                         headers={**key, "x-hydra-admin-token": "adm"})
        assert ok.status_code == 200
        assert client.get("/hydra/v1/flags", headers=key).status_code == 200  # reads stay API-key only


def test_admin_routes_are_loopback_only_without_admin_token(settings):
    app = create_app(settings.model_copy(update={"api_key": "k"}))
    with TestClient(app, client=REMOTE) as remote:
        r = remote.post("/hydra/v1/redteam/run", headers={"x-api-key": "k"})
        assert r.status_code == 503
    with TestClient(app) as local:
        assert local.post("/hydra/v1/flags/x", json={"value": "off"}, headers={"x-api-key": "k"}).status_code == 200


def test_goal_authorizations_are_an_admin_decision(settings):
    app = create_app(settings.model_copy(update={"api_key": "k", "admin_token": "adm"}))
    with TestClient(app, client=REMOTE) as client:
        body = {"goal": "deploy", "authorized": ["service.restart"]}
        assert client.post("/hydra/v1/goals", json=body, headers={"x-api-key": "k"}).status_code == 403


def test_config_environment_cannot_escape_the_store(tmp_path, settings):
    reg = ConfigRegistry(tmp_path / "configs")
    for env in ("..\\..\\escape", "../escape", "a/b", ".."):
        with pytest.raises(PathNotAllowed):
            reg.commit(env, {"x": 1})
    assert not any(tmp_path.glob("escape*")) and not (tmp_path.parent / "escape.jsonl").exists()
    with TestClient(create_app(settings)) as client:
        assert client.post("/hydra/v1/config/..%5Cescape", json={"values": {"x": 1}}).status_code == 400


def test_responses_rejects_unknown_models_like_chat_completions(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/responses", json={"model": "gpt-4o", "input": "hola"}).status_code == 400
        assert client.post("/v1/responses", json={"model": "hydra-fast", "input": "¿2+2?"}).status_code == 200


def test_studio_is_served_with_a_restrictive_csp(settings):
    with TestClient(create_app(settings)) as client:
        csp = client.get("/studio").headers["content-security-policy"]
        assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_confidence_histogram_uses_percentage_buckets():
    tracer = CognitiveTracer()
    tracer.hist[("hydra_confidence_pct",)].observe(73)
    tracer.hist[("hydra_task_latency_ms",)].observe(73)
    assert tracer.hist[("hydra_confidence_pct",)].buckets == BUCKETS_PCT
    text = tracer.prometheus()
    assert 'hydra_confidence_pct_bucket{le="80"} 1' in text
    assert 'hydra_confidence_pct_bucket{le="70"} 0' in text
    assert "# TYPE hydra_process_pid gauge" in text


def test_model_inventory_hashes_each_file_once(tmp_path, monkeypatch):
    import hydra.runtime.model_scout as scout

    (tmp_path / "m.gguf").write_bytes(b"gguf-bytes")
    calls = []
    real = scout._sha256
    monkeypatch.setattr(scout, "_sha256", lambda p: calls.append(p) or real(p))
    cache = HashCache(tmp_path / "cache" / "hashes.json")
    first = scan_models(tmp_path, cache)[0].sha256
    assert scan_models(tmp_path, cache)[0].sha256 == first and len(calls) == 1
    # Persisted across processes; a changed file is hashed again.
    assert scan_models(tmp_path, HashCache(tmp_path / "cache" / "hashes.json"))[0].sha256 == first
    assert len(calls) == 1
    (tmp_path / "m.gguf").write_bytes(b"other-bytes!")
    assert scan_models(tmp_path, cache)[0].sha256 != first and len(calls) == 2


def test_atomic_write_replaces_and_leaves_no_temporaries(tmp_path):
    target = tmp_path / "state.json"
    write_text_atomic(target, json.dumps({"v": 1}))
    write_text_atomic(target, json.dumps({"v": 2}))
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_model_artifacts_cannot_escape_the_models_root(tmp_path):
    from hydra.runtime.model_scout import inspect_model_artifact

    root = tmp_path / "models"
    sibling = tmp_path / "models-evil"
    root.mkdir()
    sibling.mkdir()
    (sibling / "x.gguf").write_bytes(b"gguf")
    (root / "ok.gguf").write_bytes(b"gguf")
    for bad in (sibling / "x.gguf", "../models-evil/x.gguf", str(root)):
        with pytest.raises(ValueError, match="escapes"):
            inspect_model_artifact(root, bad)
    assert inspect_model_artifact(root, root / "ok.gguf").path == "ok.gguf"
    assert inspect_model_artifact(root, "ok.gguf").path == "ok.gguf"


def test_websocket_accepts_any_key_through_the_base64url_subprotocol(settings):
    import base64

    key = "c2VjcmV0/with+symbols=="  # not an RFC 7230 token: '/', '+', '='
    encoded = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    app = create_app(settings.model_copy(update={"api_key": key}))
    with TestClient(app, client=REMOTE) as client:
        with client.websocket_connect("/v1/ws/tasks", subprotocols=["hydra.v1", f"hydra.token.b64.{encoded}"]) as ws:
            assert _ws_kinds(ws)[-1] == "result"


def test_programmatic_admin_token_also_protects_runtime_admin_routes(settings):
    app = create_app(settings.model_copy(update={"admin_token": "adm-code"}))
    with TestClient(app) as client:
        assert client.get("/hydra/v1/admin/deployments").status_code == 401
        ok = client.get("/hydra/v1/admin/deployments", headers={"x-hydra-admin-token": "adm-code"})
        assert ok.status_code == 200


def test_empty_sync_trusted_keys_dir_means_default(monkeypatch, tmp_path):
    from hydra.core.config import Settings

    monkeypatch.setenv("HYDRA_SYNC_TRUSTED_KEYS_DIR", "")
    assert Settings(data_dir=tmp_path).sync_trusted_keys_dir is None
