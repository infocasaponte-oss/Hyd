# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""safetensors header reader (8-byte little-endian length + JSON header). No torch needed."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

DTYPE_BYTES = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8, "I32": 4, "I16": 2, "I8": 1, "U8": 1,
               "BOOL": 1, "F8_E4M3": 1, "F8_E5M2": 1}


def read_header(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n > 100 * 1024 * 1024:
            raise ValueError("implausible safetensors header size")
        return json.loads(f.read(n))


def summarize(paths: list[Path]) -> dict[str, Any]:
    params = 0
    dtypes: dict[str, int] = {}
    tensors = 0
    metadata: dict[str, Any] = {}
    for p in paths:
        header = read_header(p)
        metadata.update(header.pop("__metadata__", {}) or {})
        for info in header.values():
            n = 1
            for d in info["shape"]:
                n *= d
            params += n
            dtypes[info["dtype"]] = dtypes.get(info["dtype"], 0) + n
            tensors += 1
    dominant = max(dtypes, key=dtypes.get) if dtypes else "unknown"
    return {"parameters": params, "dtype": dominant, "dtypes": dtypes, "tensors": tensors, "metadata": metadata}


def write_safetensors(path: str | Path, tensors: dict[str, tuple[str, list[int]]],
                      metadata: dict[str, str] | None = None) -> Path:
    """Write a header-valid safetensors file with zeroed data (tests / fixtures)."""
    header: dict[str, Any] = {}
    offset = 0
    for name, (dtype, shape) in tensors.items():
        n = 1
        for d in shape:
            n *= d
        size = n * DTYPE_BYTES[dtype]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + size]}
        offset += size
    if metadata:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode()
    raw += b" " * (-len(raw) % 8)
    p = Path(path)
    with p.open("wb") as f:
        f.write(struct.pack("<Q", len(raw)))
        f.write(raw)
        f.write(b"\x00" * offset)
    return p
