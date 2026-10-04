# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.core.budget import budget_for, PRESETS
from hydra.core.contracts import ExecutionMode, HydraRequest, Message


def test_fast_visual_budget_reserves_perception_and_answer_without_mutating_preset():
    request = HydraRequest(mode=ExecutionMode.FAST, max_latency_ms=1000,
                           messages=[Message(role="user", content="describe", images=["data:image/png;base64,x"])])
    budget = budget_for(request, time_scale=6)
    assert budget.max_model_calls == 2 and budget.max_seconds == 1
    assert PRESETS[ExecutionMode.FAST].max_model_calls == 1
    assert budget_for(HydraRequest(mode=ExecutionMode.FAST, messages=[])).max_model_calls == 1
