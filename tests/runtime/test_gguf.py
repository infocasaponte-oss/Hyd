# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import struct

import pytest

from hydra.runtime.gguf import GGUFError, inspect_gguf


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _kv_string(key: str, value: str) -> bytes:
    return _string(key) + struct.pack("<I", 8) + _string(value)


def _kv_u32(key: str, value: int) -> bytes:
    return _string(key) + struct.pack("<I", 4) + struct.pack("<I", value)


def test_inspect_gguf_reads_real_scalar_metadata(tmp_path):
    entries = [
        _kv_string("general.architecture", "llama"),
        _kv_string("general.name", "Synthetic Test"),
        _kv_u32("general.file_type", 15),
        _kv_u32("general.quantization_version", 2),
        _kv_u32("llama.context_length", 8192),
        _kv_u32("llama.embedding_length", 4096),
        _kv_u32("llama.block_count", 32),
    ]
    payload = (
        b"GGUF"
        + struct.pack("<I", 3)
        + struct.pack("<Q", 0)
        + struct.pack("<Q", len(entries))
        + b"".join(entries)
    )
    path = tmp_path / "model.gguf"
    path.write_bytes(payload)

    metadata = inspect_gguf(path)

    assert metadata.version == 3
    assert metadata.architecture == "llama"
    assert metadata.model_name == "Synthetic Test"
    assert metadata.context_length == 8192
    assert metadata.embedding_length == 4096
    assert metadata.block_count == 32
    assert metadata.file_type == 15
    assert metadata.quantization_version == 2


def test_inspect_gguf_rejects_bad_magic(tmp_path):
    path = tmp_path / "bad.gguf"
    path.write_bytes(b"NOPE" + b"\x00" * 32)

    with pytest.raises(GGUFError, match="magic"):
        inspect_gguf(path)
