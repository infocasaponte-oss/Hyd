# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import httpx
import pytest

from hydra.core.contracts import ExecutionMode, HydraRequest, Message, TaskType
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.observer import DecisionObserver
from hydra.router.router import CognitiveRouter


def request(**kwargs):
    return HydraRequest(messages=[Message(role="user", content="necesito una consulta de código")], **kwargs)


def payload():
    return {"model": "test", "answers": {"task": {
        "type": "choice", "choice": "chat", "confidence": 1,
        "probabilities": {task.value: float(task == TaskType.CHAT) for task in TaskType}}}}


def router(handler, timeout=0.5):
    provider = LocalSystemOneProvider(model="test", transport=httpx.MockTransport(handler))
    return CognitiveRouter(observer=DecisionObserver(provider, timeout))


async def test_observation_cannot_change_routing_or_permissions():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=payload())

    subject = router(handler)
    req = request()
    before = req.model_dump()
    baseline = await CognitiveRouter().route(req)
    observed = await subject.route(req)
    assert observed.model_dump(exclude={"observation"}) == baseline.model_dump(exclude={"observation"})
    assert req.model_dump() == before
    assert len(seen) == 1
    assert observed.observation.selected == TaskType.CHAT
    assert observed.observation.status == "observed"
    assert observed.observation.version == 1
    await subject.close()
    assert subject.observer.provider.client.is_closed


async def test_unexpected_observer_failure_preserves_route_and_does_not_call_authority():
    class BrokenObserver:
        model = "broken"

        async def observe(self, req):
            raise LookupError("backend failed")

    class ForbiddenAuthority:
        def task_hint(self, observation):
            pytest.fail("a failed observer must not provide authority")

    req = request()
    expected = await CognitiveRouter().route(req)
    actual = await CognitiveRouter(observer=BrokenObserver(), authority=ForbiddenAuthority()).route(req)
    assert actual.model_dump(exclude={"observation"}) == expected.model_dump(exclude={"observation"})
    assert actual.observation.reason == "observer.failure"


async def test_observer_cancellation_is_not_swallowed():
    class CancelledObserver:
        async def observe(self, req):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await CognitiveRouter(observer=CancelledObserver()).route(request())


@pytest.mark.parametrize("kwargs,reason", [
    ({"local_only": True}, "private"), ({"mode": ExecutionMode.PRIVATE}, "private"),
    ({"mode": ExecutionMode.FAST}, "fast"), ({"max_latency_ms": 1000}, "latency_budget"),
])
async def test_sensitive_or_budgeted_requests_skip_observer(kwargs, reason):
    calls = []
    subject = router(lambda req: calls.append(req))
    result = await subject.route(request(**kwargs))
    assert not calls
    assert result.observation.status == "skipped"
    assert result.observation.reason == reason
    await subject.close()


@pytest.mark.parametrize("failure", ["malformed", "unavailable", "timeout"])
async def test_observation_failure_preserves_policy(failure):
    async def handler(req):
        if failure == "timeout":
            await asyncio.sleep(10)
        if failure == "unavailable":
            return httpx.Response(503, text="secret text must not be logged")
        return httpx.Response(200, json={"model": "test", "answers": {}})

    subject = router(handler, timeout=0.01)
    result = await subject.route(request())
    baseline = await CognitiveRouter().route(request())
    assert result.model_dump(exclude={"observation"}) == baseline.model_dump(exclude={"observation"})
    assert result.observation.status == ("timeout" if failure == "timeout" else "error")
    assert "secret" not in result.observation.model_dump_json()
    await subject.close()


async def test_cancellation_is_not_swallowed():
    started = asyncio.Event()

    async def handler(req):
        started.set()
        await asyncio.sleep(10)

    subject = router(handler)
    task = asyncio.create_task(subject.route(request()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await subject.close()


async def test_offline_bootstrap_never_constructs_observer(settings):
    from hydra.core.bootstrap import build_runtime

    settings.hyd_enabled = False  # Exercise only the retired external observer path.
    settings.decision_shadow_endpoint = "https://invalid.example"
    runtime = await build_runtime(settings)
    try:
        assert runtime.kernel.router.observer is None
    finally:
        await runtime.close()


async def test_enabled_bootstrap_owns_client_lifecycle(settings, mock):
    from hydra.core.bootstrap import build_runtime
    from hydra.registry.registry import ModelRegistry
    from hydra.tools.sandbox import SubprocessSandbox
    from .conftest import default_models

    settings.hyd_enabled = False  # Explicit legacy compatibility, never the default.
    settings.offline = False
    settings.runtime_monitor = False
    settings.decision_shadow_endpoint = "http://127.0.0.1:8009"
    runtime = await build_runtime(
        settings, providers={"mock": mock, "mock-cloud": mock},
        registry=ModelRegistry(default_models()), sandbox=SubprocessSandbox())
    client = runtime.kernel.router.observer.provider.client
    try:
        assert not client.is_closed
    finally:
        await runtime.close()
    assert client.is_closed

