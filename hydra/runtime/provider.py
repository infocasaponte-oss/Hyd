# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.providers.local_llm``."""
from __future__ import annotations

from hydra.providers.local_llm import (  # noqa: F401
    LocalLLM,
)

__all__ = ['LocalLLM']
