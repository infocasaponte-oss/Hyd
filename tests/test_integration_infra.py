# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Integration with real infrastructure. Skipped unless the services are provided:

    HYDRA_IT_POSTGRES=postgresql://hydra:hydra@localhost:55432/hydra
    HYDRA_IT_REDIS=redis://localhost:56379/0
    HYDRA_IT_NATS=nats://localhost:54222
"""

import asyncio
import os
from uuid import UUID, uuid4

import pytest

from hydra.core.bootstrap import build_runtime
from hydra.core.config import Settings
from hydra.core.contracts import HydraRequest, Message
from hydra.core.events import EventType, HydraEvent
from hydra.tools.sandbox import SubprocessSandbox

PG = os.environ.get("HYDRA_IT_POSTGRES")
REDIS = os.environ.get("HYDRA_IT_REDIS")
NATS = os.environ.get("HYDRA_IT_NATS")


def req(text: str) -> HydraRequest:
    return HydraRequest(messages=[Message(role="user", content=text)], use_cache=False)


@pytest.mark.skipif(not (PG and REDIS), reason="set HYDRA_IT_POSTGRES and HYDRA_IT_REDIS")
async def test_postgres_and_redis(tmp_path):
    s = Settings(offline=True, postgres_url=PG, redis_url=REDIS, sandbox_backend="subprocess",
                 workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data", runtime_monitor=False)
    rt = await build_runtime(s, sandbox=SubprocessSandbox())
    try:
        r = await rt.kernel.run(req("Recuerda que el servicio payments usa puerto 9123"))
        r2 = await rt.kernel.run(req("¿Cuánto es 6 * 7?"))
        assert "42" in r2.answer
        await asyncio.sleep(1.0)  # redis consumer -> postgres event sink

        # tasks, runs, metrics, feedback in PostgreSQL
        task = await rt.telemetry.get_task(UUID(r.meta.task_id))
        assert task is not None and task.status == "completed"
        runs = await rt.telemetry.recent_runs()
        assert any(x.task_id == UUID(r2.meta.task_id) and x.arm for x in runs)
        assert await rt.telemetry.feedback(UUID(r2.meta.task_id), 1.0) >= 1
        assert any(m.runs >= 1 for m in await rt.telemetry.model_stats())
        assert len(await rt.telemetry.recent_tasks()) >= 2

        # long-term memory in PostgreSQL
        mem = await rt.memory.all()
        assert any(m.content.get("object") == "9123" for m in mem)
        hits = await rt.retriever.retrieve("¿qué puerto usa payments?", "chat")
        assert any("9123" in i.text for i, _ in hits)

        # event log: Redis stream per task + PostgreSQL audit log
        redis_events = await rt.bus.history(UUID(r.meta.task_id))
        assert redis_events[0].type == EventType.TASK_CREATED
        pg_events = await rt.event_sink.history(UUID(r.meta.task_id))
        assert {e.type for e in pg_events} >= {EventType.TASK_CREATED, EventType.TASK_COMPLETED}
    finally:
        await rt.close()


@pytest.mark.skipif(not NATS, reason="set HYDRA_IT_NATS (requires nats-py)")
async def test_nats_jetstream(tmp_path):
    pytest.importorskip("nats")
    from hydra.bus.nats import NatsEventBus

    bus = NatsEventBus(NATS)
    got: list[HydraEvent] = []

    async def handler(e):
        got.append(e)

    await bus.subscribe(None, handler)
    tid = uuid4()
    for t in (EventType.TASK_CREATED, EventType.MODEL_COMPLETED, EventType.TASK_COMPLETED):
        await bus.publish(HydraEvent(task_id=tid, type=t, source="it", payload={"x": 1}))
    for _ in range(50):
        if len(got) >= 3:
            break
        await asyncio.sleep(0.1)
    assert [e.type for e in got if e.task_id == tid] == [EventType.TASK_CREATED, EventType.MODEL_COMPLETED,
                                                         EventType.TASK_COMPLETED]
    history = await bus.history(tid)
    assert [e.type for e in history][0] == EventType.TASK_CREATED and len(history) == 3
    await bus.close()
