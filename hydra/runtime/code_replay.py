# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.coding.replay_evidence``."""
from __future__ import annotations

from hydra.coding.replay_evidence import (  # noqa: F401
    CodeReplayEvidence,
    build_code_replay_evidence,
)

__all__ = ['CodeReplayEvidence', 'build_code_replay_evidence']
