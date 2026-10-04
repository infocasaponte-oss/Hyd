# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA 1.0 System Contract: the stable task/result/event envelopes every service speaks.

These schemas carry no logic and are versioned independently (``schema_version``) so a
kernel 2.3 can talk to a scheduler 1.9 or a corpus service 4.1."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.contracts import ExecutionMode, HydraRequest, HydraResponse, Message
from hydra.core.events import HydraEvent
from hydra.core.hashing import canonical_json, sha256_hex

SCHEMA_VERSION = "1.0"


class CognitiveBudget(BaseModel):
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    max_parallelism: int | None = None
    max_tokens: int | None = None
    max_seconds: float | None = None
    max_cost: float | None = None


class TaskConstraints(BaseModel):
    local_only: bool = False
    allow_network: bool = False
    allow_filesystem_write: bool = False
    required_capabilities: list[str] = Field(default_factory=list)
    max_memory_gb: float | None = None
    min_quality: float | None = None


class SecurityContext(BaseModel):
    principal_id: str = "anonymous"
    tenant_id: str | None = None
    roles: set[str] = Field(default_factory=set)
    capabilities: set[str] = Field(default_factory=set)
    """Capability tokens, e.g. ``filesystem.read:/workspace/**`` or ``model.use:local``."""
    classification: str = "INTERNAL"


class ContextFragment(BaseModel):
    content: str
    classification: str = "INTERNAL"
    owner: str | None = None
    cloud_allowed: bool = True
    training_allowed: bool = False
    retention_allowed: bool = True
    source: str = "SOURCE_USER"
    """SOURCE_USER | SOURCE_EXTERNAL | SOURCE_TOOL | SOURCE_SYSTEM | SOURCE_VERIFIED"""
    source_ref: str = ""


class HydraTask(BaseModel):
    schema_version: str = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    goal: str
    mode: ExecutionMode = ExecutionMode.BALANCED
    context: list[ContextFragment] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)
    """Artifact ids / cas:// URIs / workspace paths the task may read."""
    images: list[str] = Field(default_factory=list)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    budget: CognitiveBudget = Field(default_factory=CognitiveBudget)
    security_context: SecurityContext = Field(default_factory=SecurityContext)
    world_version: str | None = None
    workspace: str | None = None
    """A local repository/directory to snapshot into the task workspace (coding tasks)."""
    approved_actions: list[str] = Field(default_factory=list)
    priority: str = "interactive"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_request(self) -> HydraRequest:
        messages: list[Message] = []
        for frag in self.context:
            if frag.source == "SOURCE_EXTERNAL":
                body = f"<untrusted_data source={frag.source_ref!r}>\n{frag.content}\n</untrusted_data>"
            else:
                body = frag.content
            messages.append(Message(role="user", content=body))
        messages.append(Message(role="user", content=self.goal, images=list(self.images)))
        local = self.constraints.local_only or any(not f.cloud_allowed for f in self.context)
        return HydraRequest(
            messages=messages, mode=self.mode, max_cost=self.budget.max_cost,
            max_latency_ms=int(self.budget.max_seconds * 1000) if self.budget.max_seconds else None,
            local_only=local, allow_high_risk_tools=self.constraints.allow_filesystem_write,
            approved_actions=list(self.approved_actions),
            metadata={**self.metadata, "hydra_task": str(self.id), "tenant_id": self.security_context.tenant_id,
                      "principal_id": self.security_context.principal_id, "priority": self.priority,
                      "workspace": self.workspace, "context_refs": self.context_refs,
                      "required_capabilities": self.constraints.required_capabilities},
        )


class HydraResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    status: str
    answer: str | None = None
    decision: str = "answer"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    verified: bool = False
    models_used: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    cost: float = 0.0
    latency_ms: float = 0.0
    trace_id: str = ""
    world_version: str | None = None
    learning: dict[str, Any] = Field(default_factory=dict)
    pending_confirmations: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_response(cls, r: HydraResponse) -> HydraResult:
        evidence = [{"claim_id": c.id, "status": c.status, "confidence": c.confidence} for c in r.claims]
        return cls(task_id=r.meta.task_id, status=r.meta.status, answer=r.answer, decision=r.meta.decision,
                   artifacts=r.artifacts, evidence=evidence, claims=[c.model_dump() for c in r.claims],
                   confidence=r.meta.confidence, verified=r.meta.verified, models_used=r.meta.models_used,
                   tools_used=r.meta.tools_used, latency_ms=r.meta.latency_ms, trace_id=r.meta.task_id,
                   world_version=str(r.learning["world_version"]) if (r.learning or {}).get("world_version")
                   is not None else None,
                   learning=r.learning or {}, pending_confirmations=r.pending_confirmations,
                   cost=float((r.learning or {}).get("cost", 0.0)))


class EventEnvelope(BaseModel):
    """Universal wire format of an event (``hydra.<domain>.<verb>``) with a payload hash."""

    schema_version: str = SCHEMA_VERSION
    event_id: str
    event_type: str
    aggregate_id: str
    sequence: int
    timestamp: str
    producer: str
    trace_id: str
    payload: dict[str, Any]
    payload_hash: str

    @classmethod
    def wrap(cls, e: HydraEvent, sequence: int) -> EventEnvelope:
        payload = e.payload
        return cls(event_id=str(e.id), event_type=f"hydra.{e.type.value}", aggregate_id=str(e.task_id),
                   sequence=sequence, timestamp=e.timestamp.isoformat(), producer=e.source,
                   trace_id=e.trace_id or str(e.task_id), payload=payload,
                   payload_hash=sha256_hex(canonical_json(payload)))

    def valid(self) -> bool:
        return self.payload_hash == sha256_hex(canonical_json(self.payload))
