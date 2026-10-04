# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.coding.agent``."""
from __future__ import annotations

from hydra.coding.agent import (  # noqa: F401
    CodeAgent,
    CodeAgentResult,
    SandboxFactory,
    extract_unified_diff,
)

__all__ = ['CodeAgent', 'CodeAgentResult', 'SandboxFactory', 'extract_unified_diff']
