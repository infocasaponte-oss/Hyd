# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.variant_runner``."""
from __future__ import annotations

from hydra.model_factory.physical.variant_runner import (  # noqa: F401
    VariantRunError,
    VariantRunner,
)

__all__ = ['VariantRunError', 'VariantRunner']

# Same module object under both paths: patching ``hydra.runtime.variant_runner.<name>`` (tests, operators) must
# reach the code that runs, not a copy of its names.
import sys as _sys  # noqa: E402

_sys.modules[__name__] = _sys.modules["hydra.model_factory.physical.variant_runner"]
