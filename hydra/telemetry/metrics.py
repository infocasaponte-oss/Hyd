# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Telemetry from day one: every inference run feeds the model performance matrix."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class InferenceRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: UUID
    task_type: str
    model_id: str
    role: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    verifier_score: float | None = None
    user_feedback: float | None = None
    complexity: float | None = None
    mode: str | None = None
    arm: str | None = None
    """Routing arm used for this task (heuristic | learned) - A/B testing."""
    task_confidence: float | None = None

    @property
    def quality(self) -> float | None:
        return self.user_feedback if self.user_feedback is not None else self.verifier_score


class ModelStats(BaseModel):
    model_id: str
    task_type: str
    runs: int
    success_rate: float
    avg_latency_ms: float
    avg_quality: float | None


class TaskRecord(BaseModel):
    id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    request: dict[str, Any]
    route: dict[str, Any] | None = None
    final_response: dict[str, Any] | None = None


class TelemetryStore(ABC):
    @abstractmethod
    async def record_runs(self, runs: list[InferenceRun]) -> None: ...

    @abstractmethod
    async def feedback(self, task_id: UUID, score: float) -> int: ...

    @abstractmethod
    async def recent_runs(self, limit: int = 50_000) -> list[InferenceRun]: ...

    @abstractmethod
    async def recent_tasks(self, limit: int = 1000) -> list[TaskRecord]: ...

    @abstractmethod
    async def model_stats(self) -> list[ModelStats]: ...

    @abstractmethod
    async def save_task(self, task: TaskRecord) -> None: ...

    @abstractmethod
    async def get_task(self, task_id: UUID) -> TaskRecord | None: ...

    async def close(self) -> None:
        return None


class InMemoryTelemetry(TelemetryStore):
    def __init__(self, max_runs: int = 100_000) -> None:
        self.runs: list[InferenceRun] = []
        self.tasks: dict[UUID, TaskRecord] = {}
        self.max_runs = max_runs

    async def record_runs(self, runs: list[InferenceRun]) -> None:
        self.runs.extend(runs)
        if len(self.runs) > self.max_runs:
            del self.runs[: len(self.runs) - self.max_runs]

    async def recent_runs(self, limit: int = 50_000) -> list[InferenceRun]:
        return self.runs[-limit:]

    async def recent_tasks(self, limit: int = 1000) -> list[TaskRecord]:
        return list(self.tasks.values())[-limit:]

    async def feedback(self, task_id: UUID, score: float) -> int:
        n = 0
        for r in self.runs:
            if r.task_id == task_id:
                r.user_feedback = score
                n += 1
        return n

    async def model_stats(self) -> list[ModelStats]:
        groups: dict[tuple[str, str], list[InferenceRun]] = defaultdict(list)
        for r in self.runs:
            groups[(r.model_id, r.task_type)].append(r)
        out = []
        for (model_id, task_type), rs in sorted(groups.items()):
            q = [r.user_feedback if r.user_feedback is not None else r.verifier_score for r in rs]
            q = [x for x in q if x is not None]
            out.append(ModelStats(
                model_id=model_id, task_type=task_type, runs=len(rs),
                success_rate=sum(r.success for r in rs) / len(rs),
                avg_latency_ms=sum(r.latency_ms for r in rs) / len(rs),
                avg_quality=sum(q) / len(q) if q else None,
            ))
        return out

    async def save_task(self, task: TaskRecord) -> None:
        self.tasks[task.id] = task

    async def get_task(self, task_id: UUID) -> TaskRecord | None:
        return self.tasks.get(task_id)
