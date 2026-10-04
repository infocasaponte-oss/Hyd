# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Event contract: everything in HYDRA happens through events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_STATUS = "task.status"

    ROUTE_SELECTED = "route.selected"
    MODELS_RANKED = "models.ranked"

    PLAN_CREATED = "plan.created"
    PLAN_REVISED = "plan.revised"

    MODEL_STARTED = "model.started"
    MODEL_COMPLETED = "model.completed"
    MODEL_FAILED = "model.failed"

    TOOL_REQUESTED = "tool.requested"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    TOOL_DENIED = "tool.denied"

    MEMORY_RETRIEVED = "memory.retrieved"
    MEMORY_STORED = "memory.stored"

    ANSWER_PROPOSED = "answer.proposed"
    HYPOTHESIS_ADDED = "hypothesis.added"
    FACT_ADDED = "fact.added"
    CRITIQUE_ADDED = "critique.added"
    EVIDENCE_ADDED = "evidence.added"
    BELIEF_UPDATED = "belief.updated"

    ESCALATED = "task.escalated"
    RETRY_DECIDED = "retry.decided"

    VERIFICATION_COMPLETED = "verification.completed"
    SYNTHESIS_COMPLETED = "synthesis.completed"

    POLICY_EVALUATED = "policy.evaluated"
    CACHE_HIT = "cache.hit"
    META_DECISION = "meta.decision"
    WORLD_UPDATED = "world.updated"
    SIMULATION_COMPLETED = "simulation.completed"
    CLAIMS_ASSESSED = "claims.assessed"
    PROVENANCE_RECORDED = "provenance.recorded"
    ARTIFACT_CREATED = "artifact.created"
    RESEARCH_GRAPH_UPDATED = "research.graph"
    COUNTERFACTUAL_ANALYZED = "counterfactual.analyzed"
    CONTEXT_COMPRESSED = "context.compressed"

    FACTORY_JOB = "factory.job"
    LAB_UPDATED = "lab.updated"

    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"


class HydraEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)

    task_id: UUID

    type: EventType

    source: str

    payload: dict[str, Any] = Field(default_factory=dict)

    trace_id: str | None = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
