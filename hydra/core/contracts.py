# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Internal language of HYDRA: every component talks in these structures."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    CHAT = "chat"
    CODING = "coding"
    REASONING = "reasoning"
    RESEARCH = "research"
    VISION = "vision"
    TOOL_USE = "tool_use"


class ExecutionMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"
    MAX = "max"
    PRIVATE = "private"


class Message(BaseModel):
    role: str
    content: str
    images: list[str] = Field(default_factory=list)
    """Images as data URIs (data:image/png;base64,...) or http(s) URLs."""

    def to_provider(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.images:
            d["images"] = list(self.images)
        return d


class HydraRequest(BaseModel):
    messages: list[Message]

    mode: ExecutionMode = ExecutionMode.BALANCED

    max_cost: float | None = None
    max_latency_ms: int | None = None

    local_only: bool = False
    allow_high_risk_tools: bool = False
    approved_actions: list[str] = Field(default_factory=list)
    """Tools the user explicitly approved for this request (policy confirmations)."""

    use_cache: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def private(self) -> bool:
        return self.local_only or self.mode == ExecutionMode.PRIVATE

    @property
    def images(self) -> list[str]:
        return [img for m in self.messages for img in m.images]

    @property
    def text(self) -> str:
        return "\n".join(m.content for m in self.messages)

    @property
    def last_user_text(self) -> str:
        for m in reversed(self.messages):
            if m.role == "user":
                return m.content
        return self.messages[-1].content if self.messages else ""


class DecisionObservation(BaseModel):
    """Experimental evidence, never an authorization or a training label."""

    version: Literal[1] = 1
    status: Literal["observed", "skipped", "error", "timeout"]
    model: str
    reason: str | None = None
    elapsed_ms: float = Field(default=0, ge=0)
    # TaskType values plus HYDRA policy outcomes: review | abstain.
    selected: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)


class RoutingDecision(BaseModel):
    task_type: TaskType

    complexity: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)

    requires_tools: bool = False
    requires_vision: bool = False
    requires_reasoning: bool = False
    requires_verification: bool = False
    requires_memory: bool = False

    desired_parallelism: int = Field(default=1, ge=1, le=8)

    signals: dict[str, float] = Field(default_factory=dict)
    observation: DecisionObservation | None = None


class ModelRequest(BaseModel):
    """What a provider receives. Independent of any physical backend."""

    messages: list[dict[str, Any]]
    temperature: float = 0.2
    max_tokens: int = 2048

    tools: list[dict[str, Any]] | None = None
    response_schema: dict[str, Any] | None = None

    reasoning_level: str = "normal"
    timeout_s: float = 120.0

    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    model_id: str
    content: str

    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0

    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    structured: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HydraMeta(BaseModel):
    task_id: str
    status: str
    task_type: TaskType
    mode: ExecutionMode
    models_used: list[str]
    tools_used: list[str]
    verified: bool
    confidence: float
    latency_ms: float
    escalations: int = 0
    steps: int = 0
    cached: bool = False
    sensitivity: str = "public"
    decision: str = "answer"
    """Final metacognitive decision: answer | ask | refuse."""


class Claim(BaseModel):
    id: str
    text: str
    confidence: float
    status: str = "supported"  # supported | uncertain | refuted | unverified
    correction: str | None = None


class HydraResponse(BaseModel):
    answer: str
    meta: HydraMeta
    uncertainties: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    pending_confirmations: list[dict[str, Any]] = Field(default_factory=list)
    """Actions the policy kernel blocked until the user approves them (send them in approved_actions)."""
    learning: dict[str, Any] = Field(default_factory=dict)
    """Learning snapshot: world version, corpus records, ledger event, procedures, cost (capture pipeline)."""
