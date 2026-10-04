# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.tools.native_workspace."""
import sys
from hydra.tools import native_workspace as _implementation
from hydra.tools.native_workspace import TaskWorkspace, TaskWorkspaceManager, WorkspaceStats, WorkspaceManager
__all__ = ["TaskWorkspace", "TaskWorkspaceManager", "WorkspaceStats", "WorkspaceManager"]
sys.modules[__name__] = _implementation
