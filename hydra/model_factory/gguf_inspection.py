# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from hydra.model_factory.gguf import GGUFError


@dataclass(frozen=True)
class GGUFMetadata:
    version: int
    tensor_count: int
    metadata_count: int
    architecture: str | None = None
    model_name: str | None = None
    context_length: int | None = None
    embedding_length: int | None = None
    block_count: int | None = None
    file_type: int | None = None
    quantization_version: int | None = None


_FIXED_TYPES: dict[int, tuple[str, int]] = {
    0: ("<B", 1),
    1: ("<b", 1),
    2: ("<H", 2),
    3: ("<h", 2),
    4: ("<I", 4),
    5: ("<i", 4),
    6: ("<f", 4),
    7: ("<B", 1),
    10: ("<Q", 8),
    11: ("<q", 8),
    12: ("<d", 8),
}
_STRING_TYPE = 8
_ARRAY_TYPE = 9


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise GGUFError("Unexpected end of GGUF metadata")
    return data


def _unpack(handle: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, _read_exact(handle, size))[0]


def _read_string(
    handle: BinaryIO,
    *,
    max_string_bytes: int,
) -> str:
    length = _unpack(handle, "<Q")
    if length > max_string_bytes:
        raise GGUFError("GGUF string exceeds inspection limit")
    raw = _read_exact(handle, length)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GGUFError("GGUF metadata contains invalid UTF-8") from exc


def _skip_bytes(handle: BinaryIO, size: int, file_size: int) -> None:
    if size < 0 or handle.tell() + size > file_size:
        raise GGUFError("GGUF metadata value exceeds file size")
    handle.seek(size, 1)


def _read_value(
    handle: BinaryIO,
    value_type: int,
    *,
    file_size: int,
    max_string_bytes: int,
    max_array_elements: int,
) -> Any:
    if value_type in _FIXED_TYPES:
        fmt, _ = _FIXED_TYPES[value_type]
        value = _unpack(handle, fmt)
        if value_type == 7:
            return bool(value)
        return value

    if value_type == _STRING_TYPE:
        return _read_string(handle, max_string_bytes=max_string_bytes)

    if value_type == _ARRAY_TYPE:
        element_type = _unpack(handle, "<I")
        count = _unpack(handle, "<Q")
        if count > max_array_elements:
            raise GGUFError("GGUF array exceeds inspection limit")
        if element_type in _FIXED_TYPES:
            _, size = _FIXED_TYPES[element_type]
            _skip_bytes(handle, size * count, file_size)
            return None
        if element_type == _STRING_TYPE:
            for _ in range(count):
                _read_string(handle, max_string_bytes=max_string_bytes)
            return None
        raise GGUFError("Unsupported GGUF array element type")

    raise GGUFError(f"Unsupported GGUF metadata value type: {value_type}")


def inspect_gguf(
    path: str | Path,
    *,
    max_metadata_entries: int = 100_000,
    max_string_bytes: int = 16 * 1024 * 1024,
    max_array_elements: int = 2_000_000,
) -> GGUFMetadata:
    source = Path(path)
    file_size = source.stat().st_size
    with source.open("rb") as handle:
        if _read_exact(handle, 4) != b"GGUF":
            raise GGUFError("Invalid GGUF magic")
        version = _unpack(handle, "<I")
        if version not in {2, 3}:
            raise GGUFError(f"Unsupported GGUF version: {version}")

        tensor_count = _unpack(handle, "<Q")
        metadata_count = _unpack(handle, "<Q")
        if metadata_count > max_metadata_entries:
            raise GGUFError("GGUF metadata entry count exceeds inspection limit")

        scalars: dict[str, Any] = {}
        for _ in range(metadata_count):
            key = _read_string(handle, max_string_bytes=max_string_bytes)
            value_type = _unpack(handle, "<I")
            value = _read_value(
                handle,
                value_type,
                file_size=file_size,
                max_string_bytes=max_string_bytes,
                max_array_elements=max_array_elements,
            )
            if value is not None:
                scalars[key] = value

    architecture = scalars.get("general.architecture")
    if architecture is not None and not isinstance(architecture, str):
        architecture = str(architecture)

    context_length = None
    embedding_length = None
    block_count = None
    if architecture:
        context_length = _as_int(scalars.get(f"{architecture}.context_length"))
        embedding_length = _as_int(scalars.get(f"{architecture}.embedding_length"))
        block_count = _as_int(scalars.get(f"{architecture}.block_count"))

    return GGUFMetadata(
        version=version,
        tensor_count=tensor_count,
        metadata_count=metadata_count,
        architecture=architecture,
        model_name=_as_str(scalars.get("general.name")),
        context_length=context_length,
        embedding_length=embedding_length,
        block_count=block_count,
        file_type=_as_int(scalars.get("general.file_type")),
        quantization_version=_as_int(
            scalars.get("general.quantization_version")
        ),
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
