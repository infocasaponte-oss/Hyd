# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.coding.request``."""
from __future__ import annotations

from hydra.coding.request import (  # noqa: F401
    CodingRequest,
    resolve_repository,
)

__all__ = ['CodingRequest', 'resolve_repository']
