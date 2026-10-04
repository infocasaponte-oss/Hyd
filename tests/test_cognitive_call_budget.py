# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The cognitive kernel's model-call counter is the shared native inference budget."""
from types import SimpleNamespace

import pytest

from hydra.core.budget import BudgetExceeded, BudgetTracker, budget_for
from hydra.core.contracts import ExecutionMode, HydraRequest, Message
from hydra.core.inference_budget import ModelCallBudgetExceeded, reserve_model_call, use_inference_budget
from hydra.core.kernel import HydraKernel


def tracker(mode=ExecutionMode.BALANCED) -> BudgetTracker:
    return BudgetTracker(budget_for(HydraRequest(messages=[Message(role="user", content="hola")], mode=mode)))


def test_reservation_cannot_overrun_with_concurrent_callers():
    budget = tracker(ExecutionMode.FAST)  # one model call
    budget.reserve_model_call()
    with pytest.raises(BudgetExceeded):
        budget.reserve_model_call()  # the hedged twin finds no free unit
    assert budget.model_calls == 1 and not budget.can_call_model()


def test_reserved_charge_does_not_count_twice_and_legacy_charge_still_counts():
    budget = tracker()
    budget.reserve_model_call()
    budget.charge_model(100, 0.01, reserved=True)
    assert budget.model_calls == 1 and budget.tokens == 100
    budget.charge_model(50, 0.0)  # callers that never reserved keep the old behaviour
    assert budget.model_calls == 2 and budget.snapshot()["model_calls"] == 2


def test_native_calls_inside_a_cognitive_task_use_the_same_counter():
    budget = tracker(ExecutionMode.FAST)
    with use_inference_budget(budget.calls):
        assert reserve_model_call() is True  # e.g. RuntimeExecutor primary
        with pytest.raises(ModelCallBudgetExceeded):
            reserve_model_call()
    assert budget.model_calls == 1
    with pytest.raises(BudgetExceeded):
        budget.reserve_model_call()


@pytest.mark.asyncio
async def test_kernel_run_exposes_its_budget_to_native_executors():
    kernel = object.__new__(HydraKernel)
    kernel.config = SimpleNamespace(time_scale=1.0)
    seen = {}

    async def fake_run(request, task_id, *, shadow, learn, budget):
        reserve_model_call()  # a native executor reached from the task
        seen["calls"] = budget.model_calls
        return "done"

    kernel._run = fake_run
    request = HydraRequest(messages=[Message(role="user", content="hola")], mode=ExecutionMode.FAST)
    assert await kernel.run(request) == "done"
    assert seen["calls"] == 1
    assert reserve_model_call() is True  # outside the task the legacy (unbounded) path is restored


@pytest.mark.asyncio
async def test_failed_attempt_returns_its_unit_so_fast_mode_can_retry():
    from hydra.core.context import TaskContext
    from hydra.core.contracts import ModelRequest, ModelResponse
    from hydra.scheduler.invoker import ModelInvoker

    class FlakyOnce:
        calls = 0

        async def generate(self, model_id, request):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider down")
            return ModelResponse(content="ok", model_id=model_id, latency_ms=1.0, input_tokens=3, output_tokens=2)

    budget = tracker(ExecutionMode.FAST)  # a single model call
    ctx = TaskContext(request=HydraRequest(messages=[Message(role="user", content="hola")]),
                      bus=SimpleNamespace(), budget=budget)

    async def emit(*args, **kwargs):
        return None

    ctx.emit = emit
    model = SimpleNamespace(id="m", provider="p", physical_name="m", runtime_options={},
                            estimate_cost=lambda i, o: 0.0)
    registry = SimpleNamespace(breaker=SimpleNamespace(register_success=lambda *a: None))
    invoker = ModelInvoker({"p": FlakyOnce()}, registry,
                           compiler=SimpleNamespace(compile=lambda m, r: r, decompile=lambda r, resp: resp))
    request = ModelRequest(messages=[{"role": "user", "content": "x"}])
    with pytest.raises(RuntimeError):
        await invoker._call_once(ctx, model, request, "worker")
    assert budget.model_calls == 0 and budget.can_call_model()  # the failure was refunded
    response = await invoker._call_once(ctx, model, request, "worker")  # the retry fits
    assert response.content == "ok" and budget.model_calls == 1 and not budget.can_call_model()


@pytest.mark.asyncio
async def test_in_flight_call_holds_its_unit_against_a_hedged_twin():
    import asyncio

    from hydra.core.context import TaskContext
    from hydra.core.contracts import ModelRequest, ModelResponse
    from hydra.scheduler.invoker import ModelInvoker

    release = asyncio.Event()

    class Slow:
        async def generate(self, model_id, request):
            await release.wait()
            return ModelResponse(content="ok", model_id=model_id, latency_ms=1.0)

    budget = tracker(ExecutionMode.FAST)
    ctx = TaskContext(request=HydraRequest(messages=[Message(role="user", content="hola")]),
                      bus=SimpleNamespace(), budget=budget)

    async def emit(*args, **kwargs):
        return None

    ctx.emit = emit
    model = SimpleNamespace(id="m", provider="p", physical_name="m", runtime_options={},
                            estimate_cost=lambda i, o: 0.0)
    registry = SimpleNamespace(breaker=SimpleNamespace(register_success=lambda *a: None))
    invoker = ModelInvoker({"p": Slow()}, registry,
                           compiler=SimpleNamespace(compile=lambda m, r: r, decompile=lambda r, resp: resp))
    first = asyncio.create_task(invoker._call_once(ctx, model, ModelRequest(messages=[{"role": "user", "content": "x"}]), "w"))
    for _ in range(3):
        await asyncio.sleep(0)
    with pytest.raises(BudgetExceeded):
        await invoker._call_once(ctx, model, ModelRequest(messages=[{"role": "user", "content": "y"}]), "w")
    release.set()
    await first
    assert budget.model_calls == 1


@pytest.mark.asyncio
async def test_budget_refused_hedge_does_not_mask_the_primary_failure():
    import asyncio

    from hydra.scheduler.parallel import hedged

    async def primary():
        await asyncio.sleep(0.05)
        raise RuntimeError("primary provider failed")

    async def backup():
        raise BudgetExceeded("model call budget exhausted")  # refused before running

    with pytest.raises(RuntimeError, match="primary provider failed"):
        await hedged(primary, backup, hedge_after_s=0.01)
