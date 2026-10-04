# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Logical model profiles. HYDRA only knows capabilities, never brands."""

from __future__ import annotations

from pydantic import BaseModel, Field

from hydra.core.contracts import TaskType


class Capabilities(BaseModel):
    chat: float = 0.7
    reasoning: float = 0
    coding: float = 0
    vision: float = 0
    tools: float = 0
    research: float = 0
    routing: float = 0

    def for_task(self, task: TaskType) -> float:
        return {
            TaskType.CHAT: self.chat,
            TaskType.CODING: self.coding,
            TaskType.REASONING: self.reasoning,
            TaskType.RESEARCH: self.research,
            TaskType.VISION: self.vision,
            TaskType.TOOL_USE: self.tools,
        }[task]


class ModelQuirks(BaseModel):
    """Backend peculiarities the Model Compiler adapts to."""

    native_json_schema: bool = True
    typed_state_json: bool = False
    """Opt-in application contract: id integer and activo boolean in state-record JSON."""
    native_tools: bool = True
    system_role: bool = True
    native_images: bool = False
    reasoning_param: str | None = None
    """How to pass a reasoning budget: 'reasoning_effort' | 'enable_thinking' | None."""
    max_output_tokens: int | None = None
    prompt_prefix: str = ""


class ModelProfile(BaseModel):
    id: str
    """Logical id used inside HYDRA."""

    provider: str
    """Key of a provider in the provider table (ollama, vllm, llamacpp, cloud, mock...)."""

    runtime_model: str | None = None
    """Physical model name on the runtime. Defaults to ``id``."""
    identity_context: str = ""
    engine_creator: str = ""
    """Operator-supplied engine and weight provenance, included before worker instructions."""

    endpoint: str | None = None
    """Dedicated runtime URL (one vLLM server per model). Defaults to the provider's URL."""

    local: bool = False
    tier: int = Field(default=2, ge=1, le=5)
    """Size/strength tier used by escalation: 1 = tiny ... 5 = frontier."""

    context_window: int = 8192
    capabilities: Capabilities = Field(default_factory=Capabilities)

    estimated_latency_ms: float = 1000
    input_cost: float = 0  # per 1M tokens
    output_cost: float = 0  # per 1M tokens

    specialty: str | None = None
    """'grounded': a specialist chosen only (and always, while eligible) for requests that bring
    their own source material; generalist models leave it unset."""

    enabled: bool = True
    current_load: float = Field(default=0, ge=0, le=1)
    queue_depth: int = 0

    quirks: ModelQuirks = Field(default_factory=ModelQuirks)
    logical_model: str | None = None
    """Logical model this runtime profile is a variant of (Model Factory)."""
    runtime_options: dict = Field(default_factory=dict)
    """Runtime knobs applied on every call, e.g. Ollama {"num_ctx": 8192, "num_gpu": 0, "keep_alive": "30m"}
    (AutoBuilder / Model Residency Manager write these)."""
    variant_id: str | None = None

    # Learned statistics (quality per task type), updated online.
    learned_quality: dict[str, float] = Field(default_factory=dict)
    runs: dict[str, int] = Field(default_factory=dict)

    @property
    def predicted_latency_ms(self) -> float:
        """Learned latency inflated by the queue in front of us (runtime monitor)."""
        return self.estimated_latency_ms * (1 + self.queue_depth / 4)

    @property
    def physical_name(self) -> str:
        return self.runtime_model or self.id

    def quality(self, task: TaskType) -> float:
        """Learned quality once there is enough data, blended with the prior before."""
        prior = self.capabilities.for_task(task)
        n = self.runs.get(task.value, 0)
        if n == 0 or task.value not in self.learned_quality:
            return prior
        weight = min(1.0, n / 50)
        return prior * (1 - weight) + self.learned_quality[task.value] * weight

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_cost + output_tokens * self.output_cost) / 1_000_000
