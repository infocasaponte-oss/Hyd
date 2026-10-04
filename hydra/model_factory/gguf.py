# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Native GGUF reader/writer (format v2/v3). No llama.cpp needed to inspect a model."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel, Field

MAGIC = b"GGUF"

# gguf value types
UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL, STRING, ARRAY, UINT64, INT64, FLOAT64 = range(13)
_SCALAR = {UINT8: "<B", INT8: "<b", UINT16: "<H", INT16: "<h", UINT32: "<I", INT32: "<i", FLOAT32: "<f",
           BOOL: "<?", UINT64: "<Q", INT64: "<q", FLOAT64: "<d"}

GGML_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1", 10: "Q2_K",
    11: "Q3_K", 12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS", 17: "IQ2_XS", 18: "IQ3_XXS",
    19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS", 24: "I8", 25: "I16", 26: "I32",
    27: "I64", 28: "F64", 29: "IQ1_M", 30: "BF16", 34: "TQ1_0", 35: "TQ2_0", 39: "MXFP4",
}

FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
    12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
    19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL",
    26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16",
    36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4_MOE",
}

MAX_INLINE_ARRAY = 64
# Inspection limits: a GGUF header is untrusted input (model supply chain).
MAX_METADATA_ENTRIES = 100_000
MAX_TENSORS = 1_000_000
MAX_TENSOR_DIMS = 8
MAX_STRING_BYTES = 16 * 1024 * 1024


class GGUFError(ValueError):
    """Malformed, truncated or out-of-limits GGUF file."""


class GGUFTensor(BaseModel):
    name: str
    shape: list[int]
    type: str
    offset: int

    @property
    def elements(self) -> int:
        n = 1
        for d in self.shape:
            n *= d
        return n


class GGUFFile(BaseModel):
    path: str
    version: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    tensors: list[GGUFTensor] = Field(default_factory=list)
    size_bytes: int = 0

    @property
    def architecture(self) -> str:
        return str(self.metadata.get("general.architecture", "unknown"))

    def arch_key(self, key: str) -> Any:
        return self.metadata.get(f"{self.architecture}.{key}")

    @property
    def parameters(self) -> int:
        return sum(t.elements for t in self.tensors)

    @property
    def file_type(self) -> str | None:
        ft = self.metadata.get("general.file_type")
        if ft is not None:
            return FILE_TYPES.get(int(ft), f"type{ft}")
        counts: dict[str, int] = {}
        for t in self.tensors:
            counts[t.type] = counts.get(t.type, 0) + t.elements
        return max(counts, key=counts.get) if counts else None

    def tensor_type_histogram(self) -> dict[str, int]:
        h: dict[str, int] = {}
        for t in self.tensors:
            h[t.type] = h.get(t.type, 0) + 1
        return h


def _remaining(f: BinaryIO) -> int:
    here = f.tell()
    end = f.seek(0, 2)
    f.seek(here)
    return end - here


def _read(f: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise GGUFError("truncated GGUF file")
    return struct.unpack(fmt, data)[0]


def _str_len(f: BinaryIO) -> int:
    n = _read(f, "<Q")
    if n > MAX_STRING_BYTES:
        raise GGUFError("GGUF string exceeds inspection limit")
    if n > _remaining(f):
        raise GGUFError("truncated GGUF file")
    return n


def _read_str(f: BinaryIO) -> str:
    return f.read(_str_len(f)).decode("utf-8", errors="replace")


def _skip_str(f: BinaryIO) -> None:
    f.seek(_str_len(f), 1)


def _read_value(f: BinaryIO, vtype: int) -> Any:
    if vtype in _SCALAR:
        return _read(f, _SCALAR[vtype])
    if vtype == STRING:
        return _read_str(f)
    if vtype == ARRAY:
        itype = _read(f, "<I")
        count = _read(f, "<Q")
        # every element takes at least one byte (strings: an 8-byte length), so a count larger
        # than the rest of the file is a lie; reject it before looping over it
        min_size = 8 if itype == STRING else struct.calcsize(_SCALAR[itype]) if itype in _SCALAR else 1
        if count * min_size > _remaining(f):
            raise GGUFError("GGUF array exceeds file size")
        if count <= MAX_INLINE_ARRAY:
            return [_read_value(f, itype) for _ in range(count)]
        # large arrays (tokenizer vocab, merges...) are skipped, not loaded
        if itype == STRING:
            for _ in range(count):
                _skip_str(f)
        elif itype in _SCALAR:
            f.seek(struct.calcsize(_SCALAR[itype]) * count, 1)
        else:
            for _ in range(count):
                _read_value(f, itype)
        return {"__array__": True, "type": itype, "count": count}
    raise GGUFError(f"unknown GGUF value type {vtype}")


def read_gguf(path: str | Path) -> GGUFFile:
    p = Path(path)
    with p.open("rb") as f:
        if f.read(4) != MAGIC:
            raise GGUFError(f"{p} is not a GGUF file")
        version = _read(f, "<I")
        if version < 2:
            raise GGUFError(f"unsupported GGUF version {version}")
        n_tensors = _read(f, "<Q")
        n_kv = _read(f, "<Q")
        if n_kv > MAX_METADATA_ENTRIES:
            raise GGUFError("GGUF metadata entry count exceeds inspection limit")
        if n_tensors > MAX_TENSORS:
            raise GGUFError("GGUF tensor count exceeds inspection limit")
        meta: dict[str, Any] = {}
        for _ in range(n_kv):
            key = _read_str(f)
            vtype = _read(f, "<I")
            meta[key] = _read_value(f, vtype)
        tensors = []
        for _ in range(n_tensors):
            name = _read_str(f)
            n_dims = _read(f, "<I")
            if n_dims > MAX_TENSOR_DIMS:
                raise GGUFError(f"GGUF tensor {name!r} has {n_dims} dimensions")
            dims = [_read(f, "<Q") for _ in range(n_dims)]
            ttype = _read(f, "<I")
            offset = _read(f, "<Q")
            tensors.append(GGUFTensor(name=name, shape=dims, type=GGML_TYPES.get(ttype, f"type{ttype}"),
                                      offset=offset))
    return GGUFFile(path=str(p), version=version, metadata=meta, tensors=tensors, size_bytes=p.stat().st_size)


# ---------------------------------------------------------------------------------------- writer
def _w_str(f: BinaryIO, s: str) -> None:
    b = s.encode()
    f.write(struct.pack("<Q", len(b)))
    f.write(b)


def _w_value(f: BinaryIO, v: Any) -> None:
    if isinstance(v, bool):
        f.write(struct.pack("<I?", BOOL, v))
    elif isinstance(v, int):
        f.write(struct.pack("<Iq", INT64, v) if v < 0 or v > 0xFFFFFFFF else struct.pack("<II", UINT32, v))
    elif isinstance(v, float):
        f.write(struct.pack("<If", FLOAT32, v))
    elif isinstance(v, str):
        f.write(struct.pack("<I", STRING))
        _w_str(f, v)
    elif isinstance(v, list):
        f.write(struct.pack("<I", ARRAY))
        if all(isinstance(x, str) for x in v):
            f.write(struct.pack("<IQ", STRING, len(v)))
            for x in v:
                _w_str(f, x)
        elif all(isinstance(x, float) for x in v):
            f.write(struct.pack("<IQ", FLOAT32, len(v)))
            f.write(struct.pack(f"<{len(v)}f", *v))
        else:
            f.write(struct.pack("<IQ", INT32, len(v)))
            f.write(struct.pack(f"<{len(v)}i", *v))
    else:
        raise TypeError(f"unsupported metadata value {type(v)}")


def write_gguf(path: str | Path, metadata: dict[str, Any], tensors: dict[str, list[list[float]] | list[float]],
               alignment: int = 32) -> Path:
    """Write a small F32 GGUF (tests, tiny specialist heads, synthetic fixtures)."""
    p = Path(path)
    meta = {"general.alignment": alignment, **metadata}
    flat: list[tuple[str, list[int], list[float]]] = []
    for name, data in tensors.items():
        if data and isinstance(data[0], list):
            rows = len(data)
            cols = len(data[0])
            values = [x for row in data for x in row]
            shape = [cols, rows]  # ggml order: fastest dimension first
        else:
            values = list(data)
            shape = [len(values)]
        flat.append((name, shape, values))
    with p.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<IQQ", 3, len(flat), len(meta)))
        for k, v in meta.items():
            _w_str(f, k)
            _w_value(f, v)
        offset = 0
        for name, shape, values in flat:
            _w_str(f, name)
            f.write(struct.pack("<I", len(shape)))
            for d in shape:
                f.write(struct.pack("<Q", d))
            f.write(struct.pack("<IQ", 0, offset))
            offset += -(-len(values) * 4 // alignment) * alignment
        pad = -f.tell() % alignment
        f.write(b"\x00" * pad)
        for _, _, values in flat:
            data = struct.pack(f"<{len(values)}f", *values)
            f.write(data)
            f.write(b"\x00" * (-len(data) % alignment))
    return p
