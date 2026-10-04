# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Old imports must share canonical globals, including monkeypatch targets."""
import importlib

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("hydra.runtime.gguf", "hydra.model_factory.gguf_inspection"),
        ("hydra.runtime.model_scout", "hydra.model_factory.model_scout"),
        ("hydra.runtime.deployment_validation", "hydra.deploy.deployment_validation"),
        ("hydra.runtime.deployment_store", "hydra.deploy.deployment_store"),
    ],
)
def test_legacy_module_is_canonical(legacy, canonical):
    assert importlib.import_module(legacy) is importlib.import_module(canonical)


def test_legacy_hash_patch_affects_canonical_inspection(tmp_path, monkeypatch):
    legacy = importlib.import_module("hydra.runtime.model_scout")
    canonical = importlib.import_module("hydra.model_factory.model_scout")
    path = tmp_path / "model.gguf"
    path.write_bytes(b"not a GGUF")
    monkeypatch.setattr(legacy, "_sha256", lambda _: "a" * 64)
    artifact = canonical.inspect_model_artifact(tmp_path, "model.gguf")
    assert artifact.sha256 == "a" * 64
    assert artifact.gguf_valid is False
