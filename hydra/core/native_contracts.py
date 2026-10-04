# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    __module__ = "hydra.runtime.contracts"
    CREATED = "created"
    ROUTING = "routing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    CAPTURING = "capturing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    __module__ = "hydra.runtime.contracts"
    CHAT = "chat"
    TRANSLATION = "translation"
    CODING = "coding"
    REASONING = "reasoning"
    RESEARCH = "research"
    TOOL_USE = "tool_use"


class CognitiveBudget(BaseModel):
    __module__ = "hydra.runtime.contracts"
    max_model_calls: int = Field(default=4, ge=1, le=64)
    max_tool_calls: int = Field(default=8, ge=0, le=128)
    max_seconds: float = Field(default=120.0, gt=0, le=3600)
    max_output_tokens: int = Field(default=4096, ge=1, le=32768)


class HydraTask(BaseModel):
    __module__ = "hydra.runtime.contracts"
    id: UUID = Field(default_factory=uuid4)
    goal: str
    task_type: TaskType | None = None
    status: TaskStatus = TaskStatus.CREATED
    budget: CognitiveBudget = Field(default_factory=CognitiveBudget)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Route(BaseModel):
    __module__ = "hydra.runtime.contracts"
    task_type: TaskType
    capability: str
    needs_verification: bool = False
    needs_tools: bool = False
    parallelism: int = Field(default=1, ge=1, le=8)
    confidence: float = Field(ge=0.0, le=1.0)


class HydraResult(BaseModel):
    __module__ = "hydra.runtime.contracts"
    task_id: UUID
    status: TaskStatus
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    trace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Public schema names keep the legacy module, while annotations resolve here.
# Resolve explicitly so importing the canonical module first is safe.
for _model in (CognitiveBudget, HydraTask, Route, HydraResult):
    _model.model_rebuild(_types_namespace=globals())
