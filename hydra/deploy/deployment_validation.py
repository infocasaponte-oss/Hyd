# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from hydra.model_factory.contracts import ModelVariant
from hydra.model_factory.model_scout import ModelArtifact, inspect_model_artifact


@dataclass(frozen=True)
class DeploymentArtifactValidator:
    models_root: Path

    def __init__(self, models_root: str | Path):
        object.__setattr__(self, "models_root", Path(models_root).resolve())

    @staticmethod
    def artifact_fingerprint(artifact: ModelArtifact) -> str:
        body = {
            "tensor_count": artifact.tensor_count,
            "architecture": artifact.architecture,
            "context_length": artifact.context_length,
            "embedding_length": artifact.embedding_length,
            "block_count": artifact.block_count,
            "file_type": artifact.file_type,
            "quantization_version": artifact.quantization_version,
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(
        self,
        variant: ModelVariant,
        *,
        expected_fingerprint: str | None = None,
    ) -> ModelArtifact:
        artifact = inspect_model_artifact(
            self.models_root,
            variant.artifact_path,
        )
        if artifact.sha256 != variant.artifact_sha256:
            raise ValueError("Model artifact SHA-256 does not match variant declaration")
        if not artifact.gguf_valid:
            raise ValueError("Model artifact is not a valid GGUF")
        if not artifact.runtime_eligible:
            raise ValueError(
                "Model artifact lacks required runtime GGUF metadata"
            )
        fingerprint = self.artifact_fingerprint(artifact)
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            raise ValueError("Model artifact GGUF metadata fingerprint changed")
        return artifact
