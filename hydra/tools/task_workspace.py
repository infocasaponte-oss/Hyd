# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Expendable per-task copies of a repository (coding loop): bounded in files and bytes, without
symlinks or VCS/virtualenv/cache directories, destroyed after the task. The original checkout is never
mounted into the execution sandbox."""
from __future__ import annotations

import shutil
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from hydra.core.paths import confine
from hydra.tools.workspace import scan_source, validate_no_symlinks

_BLOCKED_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", "runtime"}


@dataclass(frozen=True)
class TaskWorkspace:
    task_id: UUID
    root: Path
    source: Path


@dataclass(frozen=True)
class WorkspaceStats:
    files: int
    bytes: int


class TaskWorkspaceManager:
    """
    Creates expendable per-task copies. The original checkout is never mounted
    into the execution sandbox.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        source_root: str | Path,
        max_files: int = 20_000,
        max_bytes: int = 256 * 1024 * 1024,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.source_root = Path(source_root).resolve()
        self.max_files = max_files
        self.max_bytes = max_bytes

    def _scan_source(self, source: Path) -> WorkspaceStats:
        files, total_bytes = scan_source(
            source, _BLOCKED_NAMES, max_files=self.max_files, max_bytes=self.max_bytes
        )
        return WorkspaceStats(files=files, bytes=total_bytes)

    def _validate_no_symlinks(self, root: Path) -> None:
        validate_no_symlinks(root)

    def create(self, task_id: UUID, source: str | Path) -> TaskWorkspace:
        # The allowed source root is operator configuration, never request data.
        # Confine before any filesystem inspection or copying of the source.
        requested = confine(self.source_root, str(source))
        lexical = Path(os.path.abspath(os.path.join(self.source_root, str(source))))
        try:
            components = lexical.relative_to(self.source_root).parts
        except ValueError:
            raise ValueError("Workspace source is outside the allowed root") from None
        # Walk server-enumerated entries one component at a time. Request values
        # select entries, but are never used to construct paths for copying.
        # This preserves org/repo and '.', and rejects intermediate links too.
        source_path = self.source_root
        for component in components:
            if not source_path.is_dir():
                raise ValueError("Workspace source must be a directory")
            entry = next((item for item in source_path.iterdir()
                          if os.path.normcase(item.name) == os.path.normcase(component)), None)
            if entry is None:
                raise ValueError("Workspace source must be a directory")
            if entry.is_symlink() or entry.is_junction():
                raise ValueError("Workspace source may not contain a symlink or junction")
            source_path = entry
        if source_path.resolve() != requested or not source_path.is_dir():
            raise ValueError("Workspace source must be a directory")
        if self.root == source_path or source_path in self.root.parents:
            raise ValueError("Task destination must not be inside its source")

        self._scan_source(source_path)

        task_root = (self.root / str(task_id)).resolve()
        if self.root not in task_root.parents:
            raise ValueError("Invalid task workspace")

        if task_root.exists():
            shutil.rmtree(task_root)

        def ignore(_directory: str, names: list[str]) -> set[str]:
            return {name for name in names if name in _BLOCKED_NAMES}

        try:
            shutil.copytree(
                source_path,
                task_root,
                ignore=ignore,
                symlinks=True,
            )
            self._validate_no_symlinks(task_root)
        except Exception:
            if task_root.exists():
                shutil.rmtree(task_root)
            raise

        return TaskWorkspace(task_id=task_id, root=task_root, source=source_path)

    def destroy(self, workspace: TaskWorkspace) -> None:
        root = workspace.root.resolve()
        if root.exists() and self.root in root.parents:
            shutil.rmtree(root)


class ConfinedRoot:
    """Paths relative to a task workspace, never outside it (the runtime line's ``Workspace``; not to
    be confused with ``hydra.tools.workspace.Workspace``, the platform's working-copy model)."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Workspace path escape rejected")
        return candidate
