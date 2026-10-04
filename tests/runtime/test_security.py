# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from hydra.runtime.security import SecurityConfig, require_admin_access, require_api_access


class RequestStub:
    def __init__(self, host="127.0.0.1", token=None):
        self.client = SimpleNamespace(host=host)
        self.headers = {}
        if token:
            self.headers["authorization"] = f"Bearer {token}"


def test_unconfigured_api_allows_loopback_only():
    config = SecurityConfig(api_token=None, admin_token=None)
    assert require_api_access(RequestStub(), config).startswith("local:")
    with pytest.raises(HTTPException) as exc:
        require_api_access(RequestStub(host="10.0.0.2"), config)
    assert exc.value.status_code == 503


def test_api_token_required_when_configured():
    config = SecurityConfig(api_token="secret", admin_token=None)
    with pytest.raises(HTTPException):
        require_api_access(RequestStub(token="wrong"), config)
    identity = require_api_access(RequestStub(token="secret"), config)
    assert identity == "api"  # gateway identity: the token is never hashed, logged or stored


def test_admin_fails_closed_when_unconfigured():
    config = SecurityConfig(api_token=None, admin_token=None)
    with pytest.raises(HTTPException) as exc:
        require_admin_access(RequestStub(), config)
    assert exc.value.status_code == 503
