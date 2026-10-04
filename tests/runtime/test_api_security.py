# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.runtime import api
from hydra.runtime.rate_limit import RateLimit, SlidingWindowRateLimiter
from hydra.runtime.security import SecurityConfig


def test_coding_endpoint_fails_closed_without_admin_token():
    original = api.security_config
    api.security_config = SecurityConfig(api_token=None, admin_token=None)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/hydra/v1/coding/verify-fix",
                json={"goal": "fix it", "repository": "repo"},
            )
    finally:
        api.security_config = original

    assert response.status_code == 503


def test_execute_rejects_wrong_configured_api_token():
    original = api.security_config
    api.security_config = SecurityConfig(api_token="secret", admin_token=None)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/hydra/v1/tasks/execute",
                headers={"Authorization": "Bearer wrong"},
                json={"goal": "hello"},
            )
    finally:
        api.security_config = original

    assert response.status_code == 401



def test_route_rejects_wrong_configured_api_token():
    original = api.security_config
    api.security_config = SecurityConfig(api_token="secret", admin_token=None)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/hydra/v1/tasks/route",
                headers={"Authorization": "Bearer wrong"},
                json={"goal": "hello"},
            )
    finally:
        api.security_config = original

    assert response.status_code == 401


def test_route_rate_limit_is_enforced():
    original_security = api.security_config
    original_limiter = api.rate_limiter
    original_limit = api.api_rate_limit
    api.security_config = SecurityConfig(api_token=None, admin_token=None)
    api.rate_limiter = SlidingWindowRateLimiter()
    api.api_rate_limit = RateLimit(requests=1, window_seconds=60)
    try:
        with TestClient(api.app) as client:
            first = client.post("/hydra/v1/tasks/route", json={"goal": "one"})
            second = client.post("/hydra/v1/tasks/route", json={"goal": "two"})
    finally:
        api.security_config = original_security
        api.rate_limiter = original_limiter
        api.api_rate_limit = original_limit

    assert first.status_code == 200
    assert second.status_code == 429


def test_chat_rate_limit_is_enforced(monkeypatch):
    original_security = api.security_config
    original_limiter = api.rate_limiter
    original_limit = api.api_rate_limit
    api.security_config = SecurityConfig(api_token=None, admin_token=None)
    api.rate_limiter = SlidingWindowRateLimiter()
    api.api_rate_limit = RateLimit(requests=1, window_seconds=60)

    async def healthy_chat(messages, *, temperature=0.2, max_tokens=1024):
        return "ok"

    monkeypatch.setattr(api.llm, "chat", healthy_chat)
    try:
        with TestClient(api.app) as client:
            first = client.post("/v1/chat", json={"message": "one"})
            second = client.post("/v1/chat", json={"message": "two"})
    finally:
        api.security_config = original_security
        api.rate_limiter = original_limiter
        api.api_rate_limit = original_limit

    assert first.status_code == 200
    assert second.status_code == 429
