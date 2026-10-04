# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from hydra.registry.native import ModelRegistry
from hydra.scheduler.native import ExecutionPlan, PlanStep, StepKind
from hydra.scheduler.native_executor import Executor, ModelCallBudgetExceeded
from hydra.verification.verifier import Verifier


def plan():
    return ExecutionPlan(task_id=uuid4(), steps=[
        PlanStep(kind=StepKind.MODEL, capability="chat.multilingual", instruction="hello"),
        PlanStep(kind=StepKind.MODEL, capability="chat.multilingual", instruction="again"),
    ])


@pytest.mark.asyncio
async def test_over_budget_plan_is_rejected_before_inference():
    llm = AsyncMock()
    executor = Executor(llm, ModelRegistry(), Verifier())
    with pytest.raises(ModelCallBudgetExceeded):
        await executor.execute(plan(), 64, max_model_calls=1)
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_exact_budget_executes_all_model_steps():
    llm = AsyncMock()
    llm.chat.side_effect = ["first", "second"]
    result = await Executor(llm, ModelRegistry(), Verifier()).execute(
        plan(), 64, max_model_calls=2,
    )
    assert result.answer == "second"
    assert llm.chat.await_count == 2


@pytest.mark.asyncio
async def test_plan_is_rejected_against_remaining_shared_budget_before_inference():
    from hydra.core.inference_budget import inference_budget, reserve_model_call

    llm = AsyncMock()
    with inference_budget(2) as budget:
        reserve_model_call()  # e.g. a physical or shadow call already spent one unit
        with pytest.raises(ModelCallBudgetExceeded):
            await Executor(llm, ModelRegistry(), Verifier()).execute(plan(), 64, max_model_calls=2)
        assert budget.used == 1
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_unattempted_steps_return_their_units_after_a_failure():
    from hydra.core.inference_budget import inference_budget

    llm = AsyncMock()
    llm.chat.side_effect = RuntimeError("model down")
    with inference_budget(5) as budget:
        with pytest.raises(RuntimeError):
            await Executor(llm, ModelRegistry(), Verifier()).execute(plan(), 64)
        assert budget.used == 1  # the failed attempt consumes; the second step is returned
    assert llm.chat.await_count == 1


@pytest.mark.asyncio
async def test_plan_outside_budget_context_is_unchanged():
    llm = AsyncMock()
    llm.chat.side_effect = ["first", "second"]
    result = await Executor(llm, ModelRegistry(), Verifier()).execute(plan(), 64)
    assert result.answer == "second"
