# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import struct

import pytest

from hydra.runtime.deployment import Deployment, DeploymentState
from hydra.runtime.deployment_registry import DeploymentRegistry
from hydra.runtime.deployment_store import DeploymentStore
from hydra.runtime.deployment_validation import DeploymentArtifactValidator
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant


def test_round_trip_registry(tmp_path):
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256="b" * 64,
        state=BuildState.PROMOTED,
    )
    deployment = Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=DeploymentState.ACTIVE,
        generation=3,
    )
    registry = DeploymentRegistry()
    registry.add(deployment)
    store = DeploymentStore(tmp_path / "deployments.json")
    store.save(registry)
    loaded = store.load()
    restored = loaded.active_for("reasoning.general")
    assert restored.generation == 3
    assert restored.variant.variant_id == variant.variant_id


def _gguf_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _write_store_gguf(path, *, context_length: int = 8192) -> str:
    entries = [
        _gguf_string("general.architecture")
        + struct.pack("<I", 8)
        + _gguf_string("llama"),
        _gguf_string("llama.context_length")
        + struct.pack("<I", 4)
        + struct.pack("<I", context_length),
        _gguf_string("llama.embedding_length")
        + struct.pack("<I", 4)
        + struct.pack("<I", 4096),
        _gguf_string("llama.block_count")
        + struct.pack("<I", 4)
        + struct.pack("<I", 32),
    ]
    payload = (
        b"GGUF"
        + struct.pack("<I", 3)
        + struct.pack("<Q", 1)
        + struct.pack("<Q", len(entries))
        + b"".join(entries)
    )
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_store_load_fails_closed_when_physical_artifact_changes(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    artifact_path = models / "model.gguf"
    digest = _write_store_gguf(artifact_path)
    validator = DeploymentArtifactValidator(models)
    artifact = validator.validate(
        ModelVariant(
            lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
            quantization="Q4_K_M",
            artifact_path="model.gguf",
            artifact_sha256=digest,
            state=BuildState.PROMOTED,
        )
    )
    variant = ModelVariant(
        lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64),
        quantization="Q4_K_M",
        artifact_path="model.gguf",
        artifact_sha256=digest,
        state=BuildState.PROMOTED,
    )
    deployment = Deployment(
        variant=variant,
        capabilities={"reasoning.general"},
        state=DeploymentState.ACTIVE,
        generation=1,
        metadata={"gguf_fingerprint": validator.artifact_fingerprint(artifact)},
    )
    registry = DeploymentRegistry()
    registry.add(deployment)
    store = DeploymentStore(tmp_path / "deployments.json", validator=validator)
    store.save(registry)

    _write_store_gguf(artifact_path, context_length=4096)

    with pytest.raises(ValueError, match="SHA-256"):
        store.load()
