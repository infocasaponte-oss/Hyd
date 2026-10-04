# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4b): per-task workspaces live in ``hydra.tools.task_workspace``; this keeps the runtime
line's default root (``<HYDRA_RUNTIME_DIR>/workspaces``)."""
from __future__ import annotations

from pathlib import Path

from hydra.core.runtime_paths import runtime_path
from hydra.tools.task_workspace import TaskWorkspace, TaskWorkspaceManager, WorkspaceStats

__all__ = ["TaskWorkspace", "WorkspaceManager", "WorkspaceStats"]


class WorkspaceManager(TaskWorkspaceManager):
    def __init__(self, root: str | Path = runtime_path("workspaces"), *, max_files: int = 20_000,
                 max_bytes: int = 256 * 1024 * 1024, source_root: str | Path = "repositories") -> None:
        super().__init__(root, source_root=source_root, max_files=max_files, max_bytes=max_bytes)
