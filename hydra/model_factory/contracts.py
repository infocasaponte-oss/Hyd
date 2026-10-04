# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Physical variant and lineage contracts shared by the factory and deployment engine."""
from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BuildState(StrEnum):
    SOURCE = "source"
    CONVERTED = "converted"
    QUANTIZED = "quantized"
    BENCHMARKED = "benchmarked"
    PROMOTED = "promoted"
    REJECTED = "rejected"

class ModelLineage(BaseModel):
    lineage_id: UUID = Field(default_factory=uuid4)
    base_model: str
    base_model_sha256: str
    dataset_id: UUID | None = None
    dataset_manifest_sha256: str | None = None
    training_run_id: str | None = None

class ModelVariant(BaseModel):
    variant_id: UUID = Field(default_factory=uuid4)
    lineage: ModelLineage
    format: str = "gguf"
    quantization: str
    artifact_path: str
    artifact_sha256: str
    state: BuildState
    metadata: dict = Field(default_factory=dict)

def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def lineage_hash(lineage: ModelLineage) -> str:
    raw = json.dumps(
        lineage.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(raw).hexdigest()
