# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import struct

from hydra.runtime.model_scout import scan_models


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def test_model_scout_only_returns_gguf_and_marks_invalid(tmp_path):
    (tmp_path / "model.gguf").write_bytes(b"gguf")
    (tmp_path / "secret.txt").write_text("no")
    models = scan_models(tmp_path)
    assert len(models) == 1
    assert models[0].path == "model.gguf"
    assert models[0].gguf_valid is False
    assert models[0].metadata_error is not None


def test_model_scout_exposes_inspected_metadata(tmp_path):
    entries = [
        _string("general.architecture")
        + struct.pack("<I", 8)
        + _string("llama"),
        _string("general.name")
        + struct.pack("<I", 8)
        + _string("Scout Test"),
        _string("llama.context_length")
        + struct.pack("<I", 4)
        + struct.pack("<I", 8192),
    ]
    payload = (
        b"GGUF"
        + struct.pack("<I", 3)
        + struct.pack("<Q", 0)
        + struct.pack("<Q", len(entries))
        + b"".join(entries)
    )
    (tmp_path / "valid.gguf").write_bytes(payload)

    model = scan_models(tmp_path)[0]

    assert model.gguf_valid is True
    assert model.architecture == "llama"
    assert model.model_name == "Scout Test"
    assert model.context_length == 8192
    assert model.runtime_eligible is False


def test_model_scout_marks_complete_metadata_runtime_eligible(tmp_path):
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
    (tmp_path / "complete.gguf").write_bytes(payload)

    model = scan_models(tmp_path)[0]

    assert model.gguf_valid is True
    assert model.tensor_count == 1
    assert model.runtime_eligible is True
