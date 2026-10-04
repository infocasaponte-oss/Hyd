# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hydra.core.contracts import ExecutionMode
from hydra.engine import HydraEngine


async def test_query_preserves_contract_and_keeps_context_as_user_data():
    runtime = SimpleNamespace(kernel=SimpleNamespace(run=AsyncMock(return_value="result")), close=AsyncMock())
    engine = HydraEngine(runtime)
    result = await engine.query("consulta", context="documento", images=["data:image/png;base64,AA=="],
                                mode=ExecutionMode.DEEP, max_latency_ms=1234, use_cache=False)
    req = runtime.kernel.run.call_args.args[0]
    assert result == "result"
    assert req.local_only and not req.use_cache and req.max_latency_ms == 1234
    assert req.last_user_text == "consulta" and "documento" in req.text
    assert all(message.role == "user" for message in req.messages)
    assert req.images == ["data:image/png;base64,AA=="]
    assert not req.allow_high_risk_tools and not req.approved_actions
    await engine.close()
    runtime.close.assert_not_awaited()
    with pytest.raises(RuntimeError, match="closed"):
        await engine.query("otra")


async def test_owned_runtime_closes_once_even_on_failure():
    runtime = SimpleNamespace(kernel=SimpleNamespace(run=AsyncMock(side_effect=ValueError("failure"))),
                              close=AsyncMock())
    engine = HydraEngine(runtime, owns_runtime=True)
    with pytest.raises(ValueError, match="failure"):
        async with engine:
            await engine.query("consulta")
    await engine.close()
    runtime.close.assert_awaited_once()


async def test_cancellation_propagates():
    runtime = SimpleNamespace(kernel=SimpleNamespace(run=AsyncMock(side_effect=asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError):
        await HydraEngine(runtime).query("consulta")


async def test_real_offline_kernel_through_facade(runtime):
    result = await HydraEngine(runtime).query("Hola", mode=ExecutionMode.FAST)
    assert result.answer
    assert result.meta.task_id
    assert "cloud" not in result.meta.models_used


@pytest.mark.parametrize("prompt", ["", "   ", None])
async def test_empty_input_does_not_invoke_kernel(prompt):
    runtime = SimpleNamespace(kernel=SimpleNamespace(run=AsyncMock()))
    with pytest.raises(ValueError):
        await HydraEngine(runtime).query(prompt)
    runtime.kernel.run.assert_not_awaited()
