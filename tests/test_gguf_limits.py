# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import struct
import time

import pytest

from hydra.model_factory.gguf import STRING, ARRAY, UINT32, GGUFError, read_gguf, write_gguf
from hydra.runtime.gguf import GGUFError as RuntimeGGUFError


def _header(n_tensors: int, n_kv: int) -> bytes:
    return b"GGUF" + struct.pack("<IQQ", 3, n_tensors, n_kv)


def _str(s: str) -> bytes:
    data = s.encode()
    return struct.pack("<Q", len(data)) + data


def _write(tmp_path, payload: bytes):
    path = tmp_path / "hostile.gguf"
    path.write_bytes(payload)
    return path


def _rejected_fast(path, match: str) -> None:
    start = time.perf_counter()
    with pytest.raises(GGUFError, match=match):
        read_gguf(path)
    assert time.perf_counter() - start < 1.0


def test_valid_file_still_round_trips(tmp_path):
    path = tmp_path / "ok.gguf"
    write_gguf(path, {"general.architecture": "llama", "llama.context_length": 4096}, {"w": [[1.0, 2.0]]})
    parsed = read_gguf(path)
    assert parsed.architecture == "llama" and parsed.arch_key("context_length") == 4096


def test_huge_string_length_is_rejected_without_allocating(tmp_path):
    payload = _header(0, 1) + struct.pack("<Q", 2**62) + b"x"
    _rejected_fast(_write(tmp_path, payload), "string exceeds")


def test_string_longer_than_file_is_truncated(tmp_path):
    payload = _header(0, 1) + struct.pack("<Q", 1024) + b"key"
    _rejected_fast(_write(tmp_path, payload), "truncated")


def test_array_count_larger_than_file_is_rejected(tmp_path):
    payload = _header(0, 1) + _str("tokenizer.ggml.tokens") + struct.pack("<IIQ", ARRAY, STRING, 2**60)
    _rejected_fast(_write(tmp_path, payload), "array exceeds")


def test_scalar_array_count_larger_than_file_is_rejected(tmp_path):
    payload = _header(0, 1) + _str("k") + struct.pack("<IIQ", ARRAY, UINT32, 2**40)
    _rejected_fast(_write(tmp_path, payload), "array exceeds")


def test_metadata_and_tensor_counts_are_bounded(tmp_path):
    _rejected_fast(_write(tmp_path, _header(0, 10**9)), "metadata entry count")
    _rejected_fast(_write(tmp_path, _header(10**9, 0)), "tensor count")


def test_tensor_dimension_count_is_bounded(tmp_path):
    payload = _header(1, 0) + _str("w") + struct.pack("<I", 2**31)
    _rejected_fast(_write(tmp_path, payload), "dimensions")


def test_runtime_and_factory_share_the_error_type():
    assert RuntimeGGUFError is GGUFError and issubclass(GGUFError, ValueError)
