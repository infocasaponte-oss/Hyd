# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Single-pass coding loop: apply a patch and run tests in the verification sandbox."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from hydra.artifacts.task_store import ArtifactRecord, ArtifactStore
from hydra.core.durable_events import JsonlEventStore
from hydra.coding.patching import PatchTool
from hydra.tools.oci_sandbox import OciSandbox


@dataclass
class CodingLoopResult:
    accepted: bool
    before_ok: bool
    after_ok: bool
    artifacts: list[ArtifactRecord]


class _WorkspaceSnapshot:
    """Filesystem snapshot that preserves Git metadata while restoring workspace files."""

    def __init__(self, root: Path):
        self.root = root
        self._tempdir = tempfile.TemporaryDirectory(prefix="hydra-workspace-")
        self.snapshot = Path(self._tempdir.name) / "workspace"
        self.snapshot.mkdir()
        self._copy_entries(self.root, self.snapshot)

    @staticmethod
    def _copy_entries(source: Path, destination: Path) -> None:
        for entry in source.iterdir():
            if entry.name == ".git":
                continue
            target = destination / entry.name
            if entry.is_symlink():
                target.symlink_to(entry.readlink(), target_is_directory=entry.is_dir())
            elif entry.is_dir():
                shutil.copytree(entry, target, symlinks=True)
            else:
                shutil.copy2(entry, target, follow_symlinks=False)

    def restore(self) -> None:
        for entry in self.root.iterdir():
            if entry.name == ".git":
                continue
            if entry.is_symlink() or entry.is_file():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
        self._copy_entries(self.snapshot, self.root)

    def close(self) -> None:
        self._tempdir.cleanup()


class CodingLoop:
    """
    Deterministic verification shell around a proposed patch.

    Patch generation remains separate from patch execution. A patch is accepted
    only when the post-patch test run succeeds.
    """

    def __init__(
        self,
        sandbox: OciSandbox,
        patcher: PatchTool,
        artifacts: ArtifactStore,
        events: JsonlEventStore,
    ):
        self.sandbox = sandbox
        self.patcher = patcher
        self.artifacts = artifacts
        self.events = events

    async def verify_patch(
        self,
        *,
        task_id: UUID,
        trace_id: str,
        diff: str,
        test_target: str = ".",
    ) -> CodingLoopResult:
        records: list[ArtifactRecord] = []

        before = await self.sandbox.pytest(test_target)
        records.append(
            self.artifacts.put_text(
                task_id=task_id,
                kind="tests-before",
                text=before.output,
                metadata={"exit_code": before.exit_code},
            )
        )

        snapshot = _WorkspaceSnapshot(self.patcher.workspace.root)
        try:
            patch = self.patcher.apply(diff)
            records.append(
                self.artifacts.put_text(
                    task_id=task_id,
                    kind="proposed-patch",
                    text=diff,
                    metadata={"applied": patch.ok},
                )
            )
            if not patch.ok:
                snapshot.restore()
                self.events.append(
                    event_type="hydra.patch.rejected",
                    aggregate_id=task_id,
                    producer="hydra.coding_loop",
                    trace_id=trace_id,
                    payload={"reason": "apply_failed", "rolled_back": True},
                )
                return CodingLoopResult(False, before.ok, False, records)

            after = await self.sandbox.pytest(test_target)
            records.append(
                self.artifacts.put_text(
                    task_id=task_id,
                    kind="tests-after",
                    text=after.output,
                    metadata={"exit_code": after.exit_code},
                )
            )
            accepted = after.ok
            if not accepted:
                snapshot.restore()
            self.events.append(
                event_type="hydra.patch.verified",
                aggregate_id=task_id,
                producer="hydra.coding_loop",
                trace_id=trace_id,
                payload={
                    "before_ok": before.ok,
                    "after_ok": after.ok,
                    "accepted": accepted,
                    "rolled_back": not accepted,
                    "artifact_ids": [str(r.artifact_id) for r in records],
                },
            )
            return CodingLoopResult(accepted, before.ok, after.ok, records)
        except Exception:
            snapshot.restore()
            raise
        finally:
            snapshot.close()
