# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.model_factory.gguf_inspection."""
import sys
from hydra.model_factory import gguf_inspection as _implementation
from hydra.model_factory.gguf_inspection import (
    GGUFMetadata,
    _FIXED_TYPES,
    _STRING_TYPE,
    _ARRAY_TYPE,
    _read_exact,
    _unpack,
    _read_string,
    _skip_bytes,
    _read_value,
    inspect_gguf,
    _as_int,
    _as_str,
)

__all__ = ['GGUFMetadata', '_FIXED_TYPES', '_STRING_TYPE', '_ARRAY_TYPE', '_read_exact', '_unpack', '_read_string', '_skip_bytes', '_read_value', 'inspect_gguf', '_as_int', '_as_str']
sys.modules[__name__] = _implementation
