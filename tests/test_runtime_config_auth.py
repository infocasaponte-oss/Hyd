# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F1: the runtime line reads the platform Settings and authenticates like every gateway route."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from hydra.api.client_keys import new_credential
from hydra.core.config import Settings as PlatformSettings
from hydra.runtime.config import Settings as RuntimeSettings
from hydra.runtime.security import SecurityConfig, require_api_access


def test_runtime_settings_are_a_view_of_the_platform_settings(monkeypatch, tmp_path):
    for name, value in {"HYDRA_API_TOKEN": "tok", "HYDRA_ADMIN_TOKEN": "adm", "HYDRA_LLM_URL": "http://llm:1/v1",
                        "HYDRA_RUNTIME_DIR": str(tmp_path / "rt"), "HYDRA_MODELS_DIR": "m",
                        "HYDRA_ADMIN_RATE_LIMIT_PER_MINUTE": "9", "HYDRA_MAX_OUTPUT_TOKENS": "77"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("HYDRA_API_KEY", raising=False)
    monkeypatch.delenv("HYDRA_RUNTIME_DB", raising=False)
    view = RuntimeSettings.from_platform(PlatformSettings(_env_file=None))
    assert view.api_token == "tok" and view.admin_token == "adm"  # HYDRA_API_TOKEN: alias of HYDRA_API_KEY
    assert (view.llm_url, view.models_dir, view.admin_rate_limit_per_minute, view.max_output_tokens) == \
        ("http://llm:1/v1", "m", 9, 77)
    assert view.runtime_db == str(tmp_path / "rt" / "hydra.db")
    assert view.deployments_file == str(tmp_path / "rt" / "deployments.json")


def test_defaults_match_the_previous_runtime_defaults(monkeypatch):
    for name in ("HYDRA_API_KEY", "HYDRA_API_TOKEN", "HYDRA_ADMIN_TOKEN", "HYDRA_RUNTIME_DIR", "HYDRA_RUNTIME_DB",
                 "HYDRA_DEPLOYMENTS_FILE", "HYDRA_LLM_URL", "HYDRA_MODELS_DIR", "HYDRA_SANDBOX_IMAGE"):
        monkeypatch.delenv(name, raising=False)
    view = RuntimeSettings.from_platform(PlatformSettings(_env_file=None))
    fields = ("api_host", "api_port", "llm_url", "models_dir", "runtime_dir", "runtime_db", "deployments_file",
              "readiness_max_pending", "readiness_max_pending_age_seconds", "api_token", "admin_token",
              "api_rate_limit_per_minute", "admin_rate_limit_per_minute", "sandbox_image", "sandbox_runtime",
              "code_verification_mode", "workspace_max_files", "workspace_max_bytes", "max_input_chars",
              "max_output_tokens", "max_translation_chunks")
    assert {f: getattr(view, f) for f in fields} == {f: getattr(RuntimeSettings(), f) for f in fields}


def _request(token=None, host="10.0.0.5", path="/hydra/v1/tasks/route"):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers, method="POST",
                           url=SimpleNamespace(path=path))


def test_runtime_routes_recognise_client_keys_as_inference_only(tmp_path):
    token, row = new_credential()
    registry = tmp_path / "clients.json"
    registry.write_text(json.dumps({"clients": [{"id": "celtia", "enabled": True, "requests_per_minute": 30, **row}]}),
                        encoding="utf-8")
    config = SecurityConfig(api_token="gateway-key", admin_token=None, client_keys_file=str(registry))
    with pytest.raises(HTTPException) as exc:
        require_api_access(_request(token), config)
    assert exc.value.status_code == 403  # a valid client key, but not for these routes
    assert require_api_access(_request("gateway-key"), config) == "api"
    with pytest.raises(HTTPException) as exc:
        require_api_access(_request("hydra.0123456789abcdef." + "x" * 40), config)
    assert exc.value.status_code == 401


def test_a_stray_token_is_rejected_even_on_loopback_without_a_key():
    config = SecurityConfig(api_token=None, admin_token=None)
    assert require_api_access(_request(host="127.0.0.1"), config) == "local:127.0.0.1"
    with pytest.raises(HTTPException) as exc:
        require_api_access(_request("guess", host="127.0.0.1"), config)
    assert exc.value.status_code == 401
