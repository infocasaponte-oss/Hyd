# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import struct

import pytest

from hydra.runtime.deployment_validation import DeploymentArtifactValidator
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _write_runtime_gguf(path):
    entries = [
        _string("general.architecture")
        + struct.pack("<I", 8)
        + _string("llama"),
        _string("llama.context_length")
        + struct.pack("<I", 4)
        + struct.pack("<I", 8192),
        _string("llama.embedding_length")
        + struct.pack("<I", 4)
        + struct.pack("<I", 4096),
        _string("llama.block_count")
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


def _variant(path: str, digest: str) -> ModelVariant:
    return ModelVariant(
        lineage=ModelLineage(
            base_model="base",
            base_model_sha256="a" * 64,
        ),
        quantization="Q4_K_M",
        artifact_path=path,
        artifact_sha256=digest,
        state=BuildState.PROMOTED,
    )


def test_deployment_validator_accepts_matching_runtime_gguf(tmp_path):
    path = tmp_path / "model.gguf"
    digest = _write_runtime_gguf(path)

    artifact = DeploymentArtifactValidator(tmp_path).validate(
        _variant("model.gguf", digest)
    )

    assert artifact.runtime_eligible is True
    assert artifact.sha256 == digest


def test_deployment_validator_rejects_hash_mismatch(tmp_path):
    path = tmp_path / "model.gguf"
    _write_runtime_gguf(path)

    with pytest.raises(ValueError, match="SHA-256"):
        DeploymentArtifactValidator(tmp_path).validate(
            _variant("model.gguf", "0" * 64)
        )


def test_deployment_validator_rejects_path_escape(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "outside.gguf"
    digest = _write_runtime_gguf(outside)

    with pytest.raises(ValueError, match="escapes"):
        DeploymentArtifactValidator(root).validate(
            _variant("../outside.gguf", digest)
        )


def test_deployment_validator_rejects_metadata_fingerprint_drift(tmp_path):
    path = tmp_path / "model.gguf"
    digest = _write_runtime_gguf(path)
    validator = DeploymentArtifactValidator(tmp_path)
    artifact = validator.validate(_variant("model.gguf", digest))
    fingerprint = validator.artifact_fingerprint(artifact)

    with pytest.raises(ValueError, match="fingerprint"):
        validator.validate(
            _variant("model.gguf", digest),
            expected_fingerprint="0" * 64,
        )

    assert len(fingerprint) == 64
