# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.blackboard.projector import replay
from hydra.core.contracts import ExecutionMode, HydraRequest, Message, TaskType
from hydra.core.errors import ErrorKind
from hydra.core.events import EventType
from hydra.core.kernel import HydraTaskFailed

CODE = "Encuentra el bug en esta función Python:\n```python\ndef media(xs):\n    return sum(xs)/len(xs)\nprint(media([2,4]))\n```"


def req(text: str, **kw) -> HydraRequest:
    return HydraRequest(messages=[Message(role="user", content=text)], **kw)


async def types(runtime, task_id):
    from uuid import UUID
    return [e.type for e in await runtime.bus.history(UUID(task_id))]


async def test_simple_question_single_cheap_model(runtime):
    r = await runtime.kernel.run(req("¿Cuánto es 17 × 23?"))
    assert "391" in r.answer
    assert r.meta.models_used == ["small"]
    assert r.meta.status == "completed"


async def test_coding_uses_sandboxed_tools_and_verifies(runtime):
    r = await runtime.kernel.run(req(CODE))
    assert r.meta.task_type == TaskType.CODING
    assert r.meta.tools_used == ["python.execute"]
    assert "3.0" in r.answer
    assert r.meta.verified
    ev = await types(runtime, r.meta.task_id)
    assert EventType.TOOL_COMPLETED in ev and EventType.EVIDENCE_ADDED in ev


async def test_private_mode_never_touches_cloud(runtime, mock):
    await runtime.kernel.run(req("analiza en profundidad este problema de lógica", mode=ExecutionMode.PRIVATE))
    assert "cloud" not in {m for m, _ in mock.calls}


async def test_deep_mode_runs_ensemble_with_judge(runtime, mock):
    r = await runtime.kernel.run(req("Demuestra y razona: ¿cuánto es 12 * 12?", mode=ExecutionMode.DEEP))
    assert "144" in r.answer
    roles = [role for _, role in mock.calls]
    assert roles.count("reasoner") >= 2
    assert len(r.meta.models_used) >= 2


async def test_fast_mode_makes_one_call(runtime, mock):
    await runtime.kernel.run(req("Demuestra y razona algo complejo", mode=ExecutionMode.FAST))
    assert len(mock.calls) == 1


async def test_failover_to_other_model(runtime, mock):
    mock.fail["small"] = ErrorKind.UNAVAILABLE
    r = await runtime.kernel.run(req("¿Cuánto es 2+3?"))
    assert "5" in r.answer and "small" not in r.meta.models_used
    ev = await types(runtime, r.meta.task_id)
    assert EventType.MODEL_FAILED in ev and EventType.RETRY_DECIDED in ev


async def test_all_models_down_fails_cleanly(runtime, mock):
    for m in ("small", "medium", "large", "cloud"):
        mock.fail[m] = ErrorKind.UNAVAILABLE
    with pytest.raises(HydraTaskFailed) as exc:
        await runtime.kernel.run(req("hola"))
    ev = await types(runtime, str(exc.value.task_id))
    assert ev[-1] == EventType.TASK_FAILED


async def test_escalates_when_critic_rejects(runtime, mock):
    mock.quality["critic"] = 0.2  # critic says the answer is probably wrong
    r = await runtime.kernel.run(req("Analiza y razona con cuidado este problema: " + "detalle " * 400))
    ev = await types(runtime, r.meta.task_id)
    assert EventType.ESCALATED in ev
    assert r.meta.escalations >= 1


async def test_replay_matches_live_run(runtime):
    r = await runtime.kernel.run(req(CODE))
    from uuid import UUID
    state = replay(await runtime.bus.history(UUID(r.meta.task_id)))
    assert state.status == "completed"
    assert state.final_answer == r.answer
    assert state.tools_used == r.meta.tools_used


async def test_learning_loop_updates_registry_and_telemetry(runtime):
    before = runtime.registry.get("small").runs.get("chat", 0)
    await runtime.kernel.run(req("¿Cuánto es 1+1?"))
    assert runtime.registry.get("small").runs.get("chat", 0) == before + 1
    stats = await runtime.telemetry.model_stats()
    assert any(s.model_id == "small" and s.runs >= 1 for s in stats)


async def test_memory_is_compiled_and_retrieved(runtime):
    await runtime.kernel.run(req("Recuerda que el servicio payments usa puerto 9123"))
    r = await runtime.kernel.run(req("recuerda: ¿qué puerto usa payments?"))
    ev = await types(runtime, r.meta.task_id)
    assert EventType.MEMORY_RETRIEVED in ev


async def test_escalation_out_of_budget_keeps_the_previous_answer(runtime, mock, monkeypatch):
    # live failure: the first model answered, the escalation ran out of budget and the whole task failed
    from hydra.core.budget import BudgetTracker
    can_call = BudgetTracker.can_call_model
    monkeypatch.setattr(BudgetTracker, "can_escalate", lambda self: self.escalations == 0)
    monkeypatch.setattr(BudgetTracker, "can_call_model", lambda self, n=1: self.escalations == 0 and can_call(self, n))
    mock.quality["critic"] = 0.2  # force an escalation after the first answer
    r = await runtime.kernel.run(req("Analiza y razona con cuidado este problema: " + "detalle " * 400))
    assert r.answer and r.meta.escalations == 1
    events = await runtime.bus.history(__import__("uuid").UUID(r.meta.task_id))
    assert any(e.type == EventType.RETRY_DECIDED and e.payload.get("action") == "keep_previous_best" for e in events)
