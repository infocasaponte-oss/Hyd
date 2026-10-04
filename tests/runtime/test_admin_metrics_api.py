# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.runtime import api
from hydra.runtime.security import SecurityConfig


def test_admin_metrics_requires_admin_token():
    original = api.security_config
    api.security_config = SecurityConfig(api_token=None, admin_token="admin-secret")
    try:
        with TestClient(api.app) as client:
            denied = client.get("/hydra/v1/admin/metrics")
            allowed = client.get(
                "/hydra/v1/admin/metrics",
                headers={"Authorization": "Bearer admin-secret"},
            )
    finally:
        api.security_config = original

    assert denied.status_code == 401
    assert allowed.status_code == 200
    body = allowed.json()
    assert "outbox_pending" in body
    assert "spans_total" in body
    assert "spans_by_name" in body


def test_admin_metrics_history_is_protected_and_bounded():
    original = api.security_config
    api.security_config = SecurityConfig(api_token=None, admin_token="admin-secret")
    try:
        with TestClient(api.app) as client:
            client.get(
                "/hydra/v1/admin/metrics",
                headers={"Authorization": "Bearer admin-secret"},
            )
            denied = client.get("/hydra/v1/admin/metrics/history")
            allowed = client.get(
                "/hydra/v1/admin/metrics/history?limit=1",
                headers={"Authorization": "Bearer admin-secret"},
            )
            invalid = client.get(
                "/hydra/v1/admin/metrics/history?limit=0",
                headers={"Authorization": "Bearer admin-secret"},
            )
    finally:
        api.security_config = original

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["count"] <= 1
    assert invalid.status_code == 422
