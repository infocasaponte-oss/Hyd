# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from pathlib import Path


from hydra.core.runtime_paths import runtime_path
from hydra.model_factory.contracts import (BuildState, ModelLineage, ModelVariant, file_sha256, lineage_hash)

__all__ = ["BuildState", "ModelLineage", "ModelVariant", "ModelFactoryLedger", "file_sha256", "lineage_hash"]








class ModelFactoryLedger:
    def __init__(self, path: str | Path = runtime_path("model_factory.jsonl")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, variant: ModelVariant) -> ModelVariant:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(variant.model_dump_json() + "\n")
        return variant




