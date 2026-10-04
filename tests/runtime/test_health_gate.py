# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime import health_gate


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


class Client:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url):
        return self.response


@pytest.mark.asyncio
async def test_health_gate_rejects_non_2xx(monkeypatch):
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(health_gate, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        health_gate.httpx,
        "AsyncClient",
        lambda timeout: Client(Response(404)),
    )

    assert await health_gate.wait_for_health(
        "http://model/health",
        timeout_seconds=1.0,
        interval_seconds=0,
    ) is False


@pytest.mark.asyncio
async def test_health_gate_accepts_2xx(monkeypatch):
    times = iter([0.0, 0.0])
    monkeypatch.setattr(health_gate, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        health_gate.httpx,
        "AsyncClient",
        lambda timeout: Client(Response(204)),
    )

    assert await health_gate.wait_for_health(
        "http://model/health",
        timeout_seconds=1.0,
        interval_seconds=0,
    ) is True
