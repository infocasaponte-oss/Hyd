# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""PostgreSQL persistence: tasks, event log, inference runs, model metrics."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from hydra.core.config import ROOT
from hydra.core.events import HydraEvent
from hydra.telemetry.metrics import InferenceRun, ModelStats, TaskRecord, TelemetryStore

SCHEMA = ROOT / "sql" / "schema.sql"


async def create_pool(url: str, schema: Path = SCHEMA):
    import asyncpg  # optional dependency

    pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute(schema.read_text(encoding="utf-8"))
    return pool


class PostgresEventSink:
    """Bus subscriber that persists every event (audit log / replay source)."""

    def __init__(self, pool) -> None:
        self.pool = pool

    async def __call__(self, event: HydraEvent) -> None:
        await self.pool.execute(
            "INSERT INTO events (id, task_id, created_at, event_type, source, payload) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT (id) DO NOTHING",
            event.id, event.task_id, event.timestamp, event.type.value, event.source,
            json.dumps(event.payload, default=str),
        )

    async def history(self, task_id: UUID) -> list[HydraEvent]:
        rows = await self.pool.fetch(
            "SELECT * FROM events WHERE task_id = $1 ORDER BY created_at, id", task_id)
        return [HydraEvent(id=r["id"], task_id=r["task_id"], type=r["event_type"], source=r["source"],
                           payload=json.loads(r["payload"]), timestamp=r["created_at"]) for r in rows]


class PostgresTelemetry(TelemetryStore):
    def __init__(self, pool) -> None:
        self.pool = pool

    async def record_runs(self, runs: list[InferenceRun]) -> None:
        if not runs:
            return
        await self.pool.executemany(
            "INSERT INTO inference_runs (id, created_at, task_id, task_type, model_id, role, latency_ms, "
            "input_tokens, output_tokens, success, verifier_score, user_feedback, complexity, mode, arm, "
            "task_confidence) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)",
            [(r.id, r.created_at, r.task_id, r.task_type, r.model_id, r.role, r.latency_ms, r.input_tokens,
              r.output_tokens, r.success, r.verifier_score, r.user_feedback, r.complexity, r.mode, r.arm,
              r.task_confidence) for r in runs],
        )
        await self.pool.execute(
            """
            INSERT INTO model_metrics (model_id, task_type, runs, success_rate, avg_latency_ms, avg_quality)
            SELECT model_id, task_type, count(*), avg(success::int), avg(latency_ms),
                   avg(coalesce(user_feedback, verifier_score))
            FROM inference_runs GROUP BY model_id, task_type
            ON CONFLICT (model_id, task_type) DO UPDATE SET
                runs = EXCLUDED.runs, success_rate = EXCLUDED.success_rate,
                avg_latency_ms = EXCLUDED.avg_latency_ms, avg_quality = EXCLUDED.avg_quality
            """
        )

    async def recent_runs(self, limit: int = 50_000) -> list[InferenceRun]:
        rows = await self.pool.fetch("SELECT * FROM inference_runs ORDER BY created_at DESC LIMIT $1", limit)
        return [InferenceRun.model_validate(dict(r)) for r in reversed(rows)]

    async def recent_tasks(self, limit: int = 1000) -> list[TaskRecord]:
        rows = await self.pool.fetch("SELECT id FROM tasks ORDER BY created_at DESC LIMIT $1", limit)
        return [t for r in reversed(rows) if (t := await self.get_task(r["id"])) is not None]

    async def feedback(self, task_id: UUID, score: float) -> int:
        result = await self.pool.execute(
            "UPDATE inference_runs SET user_feedback = $2 WHERE task_id = $1", task_id, score)
        return int(result.split()[-1])

    async def model_stats(self) -> list[ModelStats]:
        rows = await self.pool.fetch("SELECT * FROM model_metrics ORDER BY model_id, task_type")
        return [ModelStats(model_id=r["model_id"], task_type=r["task_type"], runs=r["runs"],
                           success_rate=r["success_rate"] or 0, avg_latency_ms=r["avg_latency_ms"] or 0,
                           avg_quality=r["avg_quality"]) for r in rows]

    async def save_task(self, task: TaskRecord) -> None:
        await self.pool.execute(
            "INSERT INTO tasks (id, created_at, status, request, route, final_response) "
            "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb) ON CONFLICT (id) DO UPDATE SET "
            "status = EXCLUDED.status, route = EXCLUDED.route, final_response = EXCLUDED.final_response",
            task.id, task.created_at, task.status, json.dumps(task.request, default=str),
            json.dumps(task.route, default=str) if task.route else None,
            json.dumps(task.final_response, default=str) if task.final_response else None,
        )

    async def get_task(self, task_id: UUID) -> TaskRecord | None:
        r = await self.pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        if r is None:
            return None
        return TaskRecord(id=r["id"], created_at=r["created_at"], status=r["status"],
                          request=json.loads(r["request"]),
                          route=json.loads(r["route"]) if r["route"] else None,
                          final_response=json.loads(r["final_response"]) if r["final_response"] else None)
