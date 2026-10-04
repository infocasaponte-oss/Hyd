# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.coding.workspace_hash``."""
from __future__ import annotations

from hydra.coding.workspace_hash import (  # noqa: F401
    _SKIP_PARTS,
    workspace_sha256,
)

__all__ = ['workspace_sha256']
