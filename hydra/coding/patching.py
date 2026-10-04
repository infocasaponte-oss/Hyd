# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Unified-diff patches applied inside a confined task workspace."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hydra.tools.task_workspace import ConfinedRoot as Workspace


@dataclass(frozen=True)
class PatchResult:
    ok: bool
    output: str


class PatchTool:
    """Apply a constrained unified diff only inside a HYDRA workspace."""

    _REJECTED_PREFIXES = (
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "GIT binary patch",
        "Binary files ",
    )

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    @staticmethod
    def _validate_path(raw: str) -> None:
        raw = raw.strip()
        if not raw or raw.startswith('"') or "\x00" in raw:
            raise ValueError("Unsupported patch path")
        if raw == "/dev/null":
            return
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Patch path escape rejected")
        if ".git" in path.parts:
            raise ValueError("Patch may not modify Git metadata")

    @classmethod
    def _validate_headers(cls, diff: str) -> None:
        saw_old = False
        saw_new = False

        for line in diff.splitlines():
            if line.startswith(cls._REJECTED_PREFIXES):
                raise ValueError("Unsupported patch metadata")
            if line in {"new file mode 120000", "old mode 120000"}:
                raise ValueError("Symlink patches are not allowed")
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) != 4:
                    raise ValueError("Unsupported diff path encoding")
                cls._validate_path(parts[2])
                cls._validate_path(parts[3])
            elif line.startswith("--- "):
                raw = line[4:].split("\t", 1)[0]
                cls._validate_path(raw)
                saw_old = True
            elif line.startswith("+++ "):
                raw = line[4:].split("\t", 1)[0]
                cls._validate_path(raw)
                saw_new = True

        if not saw_old or not saw_new:
            raise ValueError("Patch requires --- and +++ headers")

    @classmethod
    def _patch_paths(cls, diff: str) -> set[Path]:
        paths: set[Path] = set()
        for line in diff.splitlines():
            if not line.startswith(("--- ", "+++ ")):
                continue
            raw = line[4:].split("\t", 1)[0].strip()
            cls._validate_path(raw)
            if raw == "/dev/null":
                continue
            if raw.startswith(("a/", "b/")):
                raw = raw[2:]
            paths.add(Path(raw))
        return paths

    def _snapshot_paths(self, paths: set[Path], root: Path) -> None:
        for relative in paths:
            source = self.workspace.root / relative
            target = root / relative
            if source.is_symlink():
                raise ValueError("Workspace contains a forbidden symlink")
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    def _restore_paths(self, paths: set[Path], root: Path) -> None:
        for relative in paths:
            target = self.workspace.root / relative
            backup = root / relative
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
            if backup.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)

    def _contains_symlink(self) -> bool:
        for directory, dirnames, filenames in os.walk(
            self.workspace.root,
            followlinks=False,
        ):
            directory_path = Path(directory)
            for name in [*dirnames, *filenames]:
                if (directory_path / name).is_symlink():
                    return True
        return False

    def reverse(self, diff: str) -> PatchResult:
        """Reverse a previously applied, validated patch inside the workspace."""
        self._validate_headers(diff)
        proc = subprocess.run(
            ["git", "apply", "--reverse", "--whitespace=nowarn", "-"],
            input=diff,
            text=True,
            cwd=self.workspace.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        return PatchResult(proc.returncode == 0, proc.stdout[-20_000:])

    def apply(self, diff: str) -> PatchResult:
        self._validate_headers(diff)
        paths = self._patch_paths(diff)
        with tempfile.TemporaryDirectory(prefix="hydra-patch-backup-") as backup_dir:
            backup = Path(backup_dir)
            self._snapshot_paths(paths, backup)
            proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                input=diff,
                text=True,
                cwd=self.workspace.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
                check=False,
            )
            output = proc.stdout[-20_000:]
            if proc.returncode != 0:
                self._restore_paths(paths, backup)
                return PatchResult(False, output)
            if self._contains_symlink():
                self._restore_paths(paths, backup)
                return PatchResult(False, output + "\nPatch created a forbidden symlink")
        return PatchResult(True, output)
