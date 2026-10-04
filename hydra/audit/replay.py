# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Replay manifests of executed tasks (file or shared stream)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from hydra.core.runtime_paths import runtime_path


class ReplayManifest(BaseModel):
    task_id: UUID
    trace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    hydra_version: str
    model_id: str | None = None
    artifact_hashes: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    selected_variant_id: str | None = None
    selected_variant_sha256: str | None = None
    deployment_generation: int | None = None
    verification_artifact_sha256: str | None = None
    baseline_workspace_sha256: str | None = None
    final_workspace_sha256: str | None = None
    policy_version: str = "dev-1"
    manifest_hash: str = ""


class ReplayStore:
    """Replay manifests: one ``<task_id>.json`` per task under the runtime directory, or, with a shared
    ``hydra.core.eventlog`` log, the PostgreSQL stream ``runtime/replay.jsonl`` (latest manifest of a
    task wins), so any node can audit a task another node executed."""

    STREAM = "runtime/replay.jsonl"

    def __init__(self, root: str | Path = runtime_path("replay"), log=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = log
        self._seen = 0
        self._index: dict[str, str] = {}

    def put(self, manifest: ReplayManifest) -> ReplayManifest:
        body = manifest.model_dump(mode="json", exclude={"manifest_hash"})
        manifest.manifest_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.log is not None:
            self.log.append(manifest.model_dump_json())
            return manifest
        self._manifest_path(manifest.task_id).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest

    def _manifest_path(self, task_id: UUID) -> Path:
        """``<root>/<task_id>.json``; ``task_id`` is normalised through ``UUID`` and the result is checked to
        stay inside ``root``."""
        base = os.path.realpath(self.root)
        path = os.path.realpath(os.path.join(base, f"{UUID(str(task_id))}.json"))
        if not path.startswith(base.rstrip(os.sep) + os.sep):
            raise ValueError("Replay manifest path escape rejected")
        return Path(path)

    def get(self, task_id: UUID) -> ReplayManifest | None:
        if self.log is not None:
            for seq, line in self.log.read(self._seen):
                self._seen = seq
                self._index[str(json.loads(line)["task_id"])] = line
            line = self._index.get(str(task_id))
            if line is not None:
                return ReplayManifest.model_validate_json(line)
        path = self._manifest_path(task_id)  # also manifests written before the shared log
        if not path.is_file():
            return None
        return ReplayManifest.model_validate_json(path.read_text(encoding="utf-8"))
