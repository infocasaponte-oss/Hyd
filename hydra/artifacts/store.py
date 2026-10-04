# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Content-addressed Artifact Store.

    sha256(content) -> objects/ab/cd/abcdef...   (identical blobs are stored once)

Patches, stdout, reports, datasets, model manifests and evidence bundles all share the
same identity mechanism. Metadata and relations (task, parents/lineage) live in an
append-only manifest log, a ``hydra.core.eventlog`` log on files or on the PostgreSQL stream
``artifacts/manifests.jsonl`` (HYDRA_ARTIFACTS_BACKEND). Blobs live in ``objects/`` or in an
S3-compatible bucket (``hydra.artifacts.blobs``); the URI scheme ``cas://sha256/<hex>`` does not change.
Several nodes share artifacts when both the manifest log and the blobs are shared."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.artifacts.blobs import LocalBlobs, S3Blobs
from hydra.core.eventlog import LogSpace
from hydra.core.hashing import now_iso, sha256_file, sha256_hex


class ArtifactManifest(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    sha256: str
    size_bytes: int
    media_type: str = "application/octet-stream"
    artifact_type: str = "blob"
    uri: str = ""
    created_by_task: str | None = None
    created_by: str = "hydra"
    parents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)

    @property
    def ref(self) -> dict[str, Any]:
        return {"id": self.artifact_id, "artifact_type": self.artifact_type, "uri": self.uri,
                "content_hash": self.sha256, "mime_type": self.media_type, "created_by": self.created_by,
                "lineage_refs": self.parents}


class ArtifactStore:
    def __init__(self, root: Path, logs: LogSpace | None = None, blobs: LocalBlobs | S3Blobs | None = None,
                 refresh_s: float = 1.0) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.blobs = blobs or LocalBlobs(root / "objects")
        self.logs = logs or LogSpace(label="artifacts")
        self._log = self.logs.open(root / "manifests.jsonl", "artifacts/manifests.jsonl")
        self.refresh_s = refresh_s
        self._lock = threading.RLock()
        self._manifests: dict[str, ArtifactManifest] = {}
        self._seen = 0
        self._synced_at = 0.0
        self._catch_up()

    @property
    def manifests(self) -> dict[str, ArtifactManifest]:
        if self._log.shared and time.monotonic() - self._synced_at >= self.refresh_s:
            self._catch_up()
        return self._manifests

    def _catch_up(self) -> None:
        with self._lock:
            for seq, line in self._log.read(self._seen):
                m = ArtifactManifest.model_validate_json(line)
                self._manifests[m.artifact_id] = m
                self._seen = seq
            self._synced_at = time.monotonic()

    def _record(self, m: ArtifactManifest) -> ArtifactManifest:
        """Append the manifest; the blob is already stored, so a manifest never points at nothing."""
        with self._lock:
            seq, _ = self._log.append(m.model_dump_json())
            if self._log.shared:
                self._catch_up()
            else:
                self._manifests[m.artifact_id], self._seen = m, seq
        return m

    def put(self, data: bytes | str, *, media_type: str = "text/plain", artifact_type: str = "blob",
            task_id: str | None = None, parents: list[str] | None = None, created_by: str = "hydra",
            metadata: dict[str, Any] | None = None) -> ArtifactManifest:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        digest = sha256_hex(raw)
        self.blobs.put(digest, raw)
        return self._record(ArtifactManifest(
            sha256=digest, size_bytes=len(raw), media_type=media_type, artifact_type=artifact_type,
            uri=f"cas://sha256/{digest}", created_by_task=task_id, parents=parents or [], created_by=created_by,
            metadata=metadata or {}))

    def put_json(self, obj: Any, **kw) -> ArtifactManifest:
        return self.put(json.dumps(obj, ensure_ascii=False, indent=2, default=str),
                        media_type="application/json", **kw)

    def put_file(self, src: Path, **kw) -> ArtifactManifest:
        digest = sha256_file(src)
        self.blobs.put_file(digest, src)
        kw.setdefault("metadata", {})["filename"] = src.name
        return self._record(ArtifactManifest(sha256=digest, size_bytes=src.stat().st_size,
                                             uri=f"cas://sha256/{digest}",
                                             **{k: v for k, v in kw.items() if k != "task_id"},
                                             created_by_task=kw.get("task_id")))

    def get(self, ref: str) -> bytes:
        """``ref`` may be an artifact id, a sha256 or a ``cas://`` URI."""
        digest = ref.rsplit("/", 1)[-1] if ref.startswith("cas://") else (
            self.manifests[ref].sha256 if ref in self.manifests else ref)
        return self.blobs.get(digest)

    def text(self, ref: str) -> str:
        return self.get(ref).decode("utf-8", "replace")

    def for_task(self, task_id: str) -> list[ArtifactManifest]:
        return [m for m in self.manifests.values() if m.created_by_task == task_id]

    def lineage(self, artifact_id: str) -> list[ArtifactManifest]:
        out, seen, stack = [], set(), [artifact_id]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.manifests:
                continue
            seen.add(cur)
            m = self.manifests[cur]
            out.append(m)
            stack.extend(m.parents)
        return out

    def verify(self) -> dict[str, Any]:
        """Re-hash every stored object (disaster recovery / audit)."""
        bad, checked = [], 0
        for digest in sorted({m.sha256 for m in self.manifests.values()}):
            checked += 1
            if self.blobs.digest_of(digest) != digest:
                bad.append(digest)
        return {"ok": not bad, "objects": checked, "corrupt_or_missing": bad}

    def stats(self) -> dict[str, Any]:
        unique = {m.sha256: m.size_bytes for m in self.manifests.values()}
        return {"manifests": len(self.manifests), "objects": len(unique), "bytes": sum(unique.values())}
