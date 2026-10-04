# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model Factory contracts. A model is never identified by its file name alone."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class ModelFormat(str, Enum):
    SAFETENSORS = "safetensors"
    GGUF = "gguf"
    AWQ = "awq"
    GPTQ = "gptq"
    FP8 = "fp8"
    MLX = "mlx"
    ONNX = "onnx"
    LORA = "lora"
    OLLAMA = "ollama"


class SourceType(str, Enum):
    LOCAL_DIR = "local_dir"
    HUGGINGFACE = "huggingface"
    GGUF_FILE = "gguf_file"
    SAFETENSORS_FILE = "safetensors_file"
    LORA = "lora"
    OLLAMA = "ollama"
    CHECKPOINT = "checkpoint"


class ModelSource(BaseModel):
    source_type: SourceType
    location: str
    revision: str | None = None
    trust_remote_code: bool = False


class Fingerprint(BaseModel):
    weights_sha256: str
    tokenizer_hash: str | None = None
    config_hash: str | None = None
    chat_template_hash: str | None = None

    @property
    def short(self) -> str:
        return self.weights_sha256[:12]


class ModelInspection(BaseModel):
    format: ModelFormat
    architecture: str
    dtype: str
    parameters: int
    context_length: int | None = None
    vocab_size: int | None = None
    embedding_length: int | None = None
    layers: int | None = None
    is_moe: bool = False
    experts: int | None = None
    is_multimodal: bool = False
    quantization: str | None = None
    has_chat_template: bool = False
    supports_gguf: bool = False
    supports_vllm: bool = False
    supports_mlx: bool = False
    size_bytes: int = 0
    files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelArtifact(BaseModel):
    """Manifest of one concrete build of a logical model."""

    id: str = Field(default_factory=lambda: f"art-{uuid.uuid4().hex[:10]}")
    logical_model: str
    variant_id: str
    architecture: str
    parameter_count: int | None = None
    format: ModelFormat
    quantization: str | None = None
    path: str
    context_length: int | None = None
    multimodal: bool = False
    runtime_targets: list[str] = Field(default_factory=list)
    size_bytes: int
    checksum: str
    fingerprint: Fingerprint | None = None
    parent_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelLineage(BaseModel):
    artifact_id: str
    parent_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    training_run: str | None = None
    operation: str = "import"
    converter_version: str | None = None
    quantizer_version: str | None = None
    created_at: datetime = Field(default_factory=_now)


class BuildNode(BaseModel):
    id: str
    operation: str  # convert | quantize | imatrix | merge_lora | export
    input_artifact: str
    output_format: ModelFormat
    quantization: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    artifact_id: str
    load_success: bool
    logits_similarity: float | None = None
    kl_divergence: float | None = None
    perplexity: float | None = None
    perplexity_delta: float | None = None
    task_score: float = 0.0
    structured_output_score: float = 0.0
    tool_call_score: float = 0.0
    latency_ms: float | None = None
    memory_gb: float | None = None
    approved: bool = False
    reasons: list[str] = Field(default_factory=list)


class BenchmarkResult(BaseModel):
    artifact_id: str
    variant_id: str
    tokens_per_second: float | None = None
    prompt_tokens_per_second: float | None = None
    ttft_ms: float | None = None
    load_ms: float | None = None
    ram_gb: float | None = None
    vram_gb: float | None = None
    quality: float | None = None
    context_degradation: float | None = None
    concurrency_tps: float | None = None
    energy_j: float | None = None
    runs: int = 0


class ModelVariant(BaseModel):
    """What the router optimises over: model + variant."""

    id: str
    logical_model: str
    artifact_id: str
    format: ModelFormat
    quantization: str | None = None
    hardware_targets: list[str] = Field(default_factory=list)
    runtime: str = "ollama"  # ollama | llamacpp | vllm | mlx | onnx
    runtime_model: str | None = None
    endpoint: str | None = None
    quality_score: float = 0.0
    reasoning_score: float = 0.0
    coding_score: float = 0.0
    memory_gb: float = 0.0
    tokens_per_second: float = 0.0
    ttft_ms: float = 0.0
    approved: bool = False
    base_model: str | None = None
    adapter: str | None = None
    status: str = "candidate"  # candidate | canary | production | retired
    validation: ValidationReport | None = None
    benchmark: BenchmarkResult | None = None


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class FactoryJob(BaseModel):
    id: str = Field(default_factory=lambda: f"job-{uuid.uuid4().hex[:10]}")
    kind: str  # import | build | optimize | validate | benchmark | publish | distill | jit | canary
    params: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    result: dict[str, Any] | None = None
    error: str | None = None
    log: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
