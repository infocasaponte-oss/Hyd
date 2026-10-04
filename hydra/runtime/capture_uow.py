# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.task_commit."""
import sys

from hydra.core import task_commit as _implementation
from hydra.core.task_commit import CaptureUnitOfWork, TaskCommit

__all__ = ["CaptureUnitOfWork", "TaskCommit"]
sys.modules[__name__] = _implementation
