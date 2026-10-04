# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.runtime_paths import runtime_path


class ArtifactRecord(BaseModel):
    artifact_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    kind: str
    media_type: str
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = Field(default_factory=dict)


class ArtifactStore:
    """Content-addressed runtime artifacts. On one node: ``sha256/ab/<digest>`` blobs and one manifest
    file per artifact under the runtime directory. Shared (``blobs`` and ``log`` given): blobs in the
    platform blob store (``hydra.artifacts.blobs``: a shared directory or an S3 bucket) and manifests in
    the ``runtime/artifacts.jsonl`` stream; blobs already stored locally are still readable, and are
    copied to the shared store the first time they are read."""

    STREAM = "runtime/artifacts.jsonl"

    def __init__(self, root: str | Path = runtime_path("artifacts"), *, blobs=None, log=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if (blobs is None) != (log is None):
            raise ValueError("shared artifacts need both a blob store and a manifest log")
        self.blobs = blobs
        self.log = log

    def _local_blob(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / digest

    def digest_of(self, sha256: str) -> str | None:
        """sha256 of what is stored under ``sha256`` (None when missing): audits re-hash with it."""
        if self.blobs is not None and self.blobs.exists(sha256):
            return self.blobs.digest_of(sha256)
        blob = self._local_blob(sha256)
        return hashlib.sha256(blob.read_bytes()).hexdigest() if blob.is_file() else None

    def put_bytes(
        self,
        *,
        task_id: UUID,
        kind: str,
        data: bytes,
        media_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> ArtifactRecord:
        digest = hashlib.sha256(data).hexdigest()
        if self.blobs is not None:
            self.blobs.put(digest, data)
        else:
            blob = self._local_blob(digest)
            blob.parent.mkdir(parents=True, exist_ok=True)
            if not blob.exists():
                blob.write_bytes(data)
        record = ArtifactRecord(
            task_id=task_id,
            kind=kind,
            media_type=media_type,
            sha256=digest,
            metadata=metadata or {},
        )
        if self.log is not None:
            self.log.append(record.model_dump_json())
            return record
        manifest = self.root / "manifests"
        manifest.mkdir(parents=True, exist_ok=True)
        (manifest / f"{record.artifact_id}.json").write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )
        return record

    def get_bytes(self, sha256: str, *, max_bytes: int | None = None) -> bytes:
        if len(sha256) != 64:
            raise ValueError("Artifact SHA-256 must contain 64 hex characters")
        try:
            int(sha256, 16)
        except ValueError as exc:
            raise ValueError("Artifact SHA-256 must be hexadecimal") from exc

        blob = self._local_blob(sha256)
        if self.blobs is not None:
            if not self.blobs.exists(sha256) and blob.is_file():  # written before the shared store
                if hashlib.sha256(blob.read_bytes()).hexdigest() == sha256:
                    self.blobs.put_file(sha256, blob)
            if self.blobs.exists(sha256):
                data = self.blobs.get(sha256)
                if max_bytes is not None and len(data) > max_bytes:
                    raise ValueError("Artifact exceeds read limit")
                return data
        if not blob.is_file():
            raise FileNotFoundError(f"Artifact blob not found: {sha256}")
        if max_bytes is not None and blob.stat().st_size > max_bytes:
            raise ValueError("Artifact exceeds read limit")
        return blob.read_bytes()

    def get_text(self, sha256: str, *, max_bytes: int | None = None) -> str:
        data = self.get_bytes(sha256, max_bytes=max_bytes)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Artifact is not valid UTF-8 text") from exc

    def put_text(self, *, task_id: UUID, kind: str, text: str, metadata: dict | None = None):
        return self.put_bytes(
            task_id=task_id,
            kind=kind,
            data=text.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            metadata=metadata,
        )
