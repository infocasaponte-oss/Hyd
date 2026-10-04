# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Four memory types: working, episodic, semantic, procedural."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryStatus(str, Enum):
    """Never 'model said X -> permanent memory'. Knowledge climbs these levels."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    CANONICAL = "canonical"
    CONFLICT = "conflict"


STATUS_WEIGHT = {
    MemoryStatus.UNVERIFIED: 0.4,
    MemoryStatus.CONFLICT: 0.3,
    MemoryStatus.SUPPORTED: 0.7,
    MemoryStatus.VERIFIED: 0.9,
    MemoryStatus.CANONICAL: 1.0,
}


def _now() -> datetime:
    return datetime.now(UTC)


class WorkingMemory(BaseModel):
    """Lives only while the task lives."""

    objective: str
    current_plan: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    selected_memories: list[dict[str, Any]] = Field(default_factory=list)


class Episode(BaseModel):
    task_type: str
    summary: str
    strategy: list[str]
    outcome: str
    success: bool
    confidence: float
    embedding: list[float] | None = None


class SemanticFact(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float
    source_count: int = 1
    valid_from: str | None = None
    valid_until: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject.lower(), self.predicate.lower())

    @property
    def text(self) -> str:
        return f"{self.subject} {self.predicate} {self.object}"


class Procedure(BaseModel):
    name: str
    task_type: str
    steps: list[str]
    success_rate: float
    runs: int = 1


class MemoryItem(BaseModel):
    """Persisted unit of long-term memory (matches the ``memories`` table)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    memory_type: MemoryType
    content: dict[str, Any]
    text: str
    confidence: float = 0.5
    status: MemoryStatus = MemoryStatus.UNVERIFIED
    importance: float = 0.0
    embedding: list[float] | None = None
    conflicts_with: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    last_accessed_at: datetime | None = None

    @classmethod
    def from_fact(cls, fact: SemanticFact, **kw) -> MemoryItem:
        return cls(memory_type=MemoryType.SEMANTIC, content=fact.model_dump(), text=fact.text,
                   confidence=fact.confidence, **kw)

    @classmethod
    def from_episode(cls, ep: Episode, **kw) -> MemoryItem:
        return cls(memory_type=MemoryType.EPISODIC, content=ep.model_dump(exclude={"embedding"}),
                   text=f"{ep.task_type}: {ep.summary} -> {ep.outcome}", confidence=ep.confidence, **kw)

    @classmethod
    def from_procedure(cls, proc: Procedure, **kw) -> MemoryItem:
        return cls(memory_type=MemoryType.PROCEDURAL, content=proc.model_dump(),
                   text=f"{proc.name}: " + " -> ".join(proc.steps), confidence=proc.success_rate, **kw)
