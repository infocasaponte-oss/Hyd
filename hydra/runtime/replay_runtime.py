# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.audit.deployment_replay``."""
from __future__ import annotations

from hydra.audit.deployment_replay import (  # noqa: F401
    runtime_replay_manifest,
)

__all__ = ['runtime_replay_manifest']
