# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Audit replay: manifest hash, chain integrity and artifact re-hashing."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from hydra.core.durable_events import JsonlEventStore
from hydra.core.runtime_paths import runtime_path
from hydra.provenance.ledger import ProvenanceLedger
from hydra.audit.replay import ReplayManifest
from hydra.audit.integrity import verify_replay_sources


@dataclass(frozen=True)
class AuditReplayResult:
    valid: bool
    checked_artifacts: int
    event_records: int
    provenance_records: int
    error: str | None = None


def verify_manifest_hash(manifest: ReplayManifest) -> bool:
    body = manifest.model_dump(mode="json", exclude={"manifest_hash"})
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest == manifest.manifest_hash


class AuditReplayExecutor:
    def __init__(
        self,
        *,
        events: JsonlEventStore,
        provenance: ProvenanceLedger,
        artifact_root: str | Path = runtime_path("artifacts"),
        artifacts=None,
    ):
        """``artifacts``: the runtime ``ArtifactStore`` (shared blobs included); without it, blobs are
        read from ``artifact_root``."""
        self.events = events
        self.provenance = provenance
        self.artifact_root = Path(artifact_root)
        self.artifacts = artifacts

    def _digest_of(self, digest: str) -> str | None:
        if self.artifacts is not None:
            return self.artifacts.digest_of(digest)
        blob = self.artifact_root / "sha256" / digest[:2] / digest
        return hashlib.sha256(blob.read_bytes()).hexdigest() if blob.is_file() else None

    def audit(self, manifest: ReplayManifest) -> AuditReplayResult:
        if not verify_manifest_hash(manifest):
            return AuditReplayResult(
                valid=False,
                checked_artifacts=0,
                event_records=0,
                provenance_records=0,
                error="replay manifest hash mismatch",
            )

        sources = verify_replay_sources(self.events, self.provenance)
        if not sources.valid:
            return AuditReplayResult(
                valid=False,
                checked_artifacts=0,
                event_records=sources.event_records,
                provenance_records=sources.provenance_records,
                error=sources.error,
            )

        checked = 0
        for digest in manifest.artifact_hashes:
            if len(digest) != 64:
                return AuditReplayResult(
                    valid=False,
                    checked_artifacts=checked,
                    event_records=sources.event_records,
                    provenance_records=sources.provenance_records,
                    error="invalid artifact digest",
                )
            actual = self._digest_of(digest)
            if actual is None:
                return AuditReplayResult(
                    valid=False,
                    checked_artifacts=checked,
                    event_records=sources.event_records,
                    provenance_records=sources.provenance_records,
                    error=f"artifact missing: {digest}",
                )
            if actual != digest:
                return AuditReplayResult(
                    valid=False,
                    checked_artifacts=checked,
                    event_records=sources.event_records,
                    provenance_records=sources.provenance_records,
                    error=f"artifact hash mismatch: {digest}",
                )
            checked += 1

        return AuditReplayResult(
            valid=True,
            checked_artifacts=checked,
            event_records=sources.event_records,
            provenance_records=sources.provenance_records,
        )
