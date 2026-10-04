# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
import json
import threading
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.eventlog import FileLog
from hydra.corpus.gates import CorpusCurator
from hydra.core.runtime_paths import runtime_path
from hydra.corpus.privacy_contracts import PrivacyScanResult, PrivacyScanStatus as PrivacyScanStatus


class CorpusStatus(StrEnum):
    QUARANTINED = "quarantined"
    CURATED = "curated"
    BLOCKED = "blocked"
    TOMBSTONED = "tombstoned"


class QualityTier(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class RightsDeclaration(BaseModel):
    rights_confirmed: bool = False
    privacy_reviewed: bool = False
    training_allowed: bool = False
    source_license: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class CorpusRecord(BaseModel):
    record_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    belief_id: UUID
    artifact_hashes: list[str]
    status: CorpusStatus = CorpusStatus.QUARANTINED
    quality_tier: QualityTier = QualityTier.BRONZE
    rights: RightsDeclaration = Field(default_factory=RightsDeclaration)
    privacy_scan: PrivacyScanResult = Field(default_factory=PrivacyScanResult)
    content_hash: str = ""


class CorpusGate:
    def evaluate(self, record: CorpusRecord) -> CorpusRecord:
        rights_evidence = bool(
            record.rights.source_license or record.rights.evidence_refs
        )
        record.status = CorpusStatus(CorpusCurator.artifact_status(
            rights_confirmed=record.rights.rights_confirmed,
            privacy_reviewed=record.rights.privacy_reviewed,
            training_allowed=record.rights.training_allowed,
            rights_evidence=rights_evidence,
            privacy_status=record.privacy_scan.status.value,
        ))
        body = {
            "task_id": str(record.task_id),
            "belief_id": str(record.belief_id),
            "artifact_hashes": sorted(record.artifact_hashes),
            "status": record.status.value,
            "quality_tier": record.quality_tier.value,
            "rights": record.rights.model_dump(),
            "privacy_scan": record.privacy_scan.model_dump(mode="json"),
        }
        record.content_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return record


class CorpusIndex:
    """In-memory exact-dedup index suitable for ingestion gates."""

    def __init__(self) -> None:
        self._hashes: set[str] = set()

    def accept(self, record: CorpusRecord) -> bool:
        if not record.content_hash:
            raise ValueError("Corpus record must be hashed before deduplication")
        if record.content_hash in self._hashes:
            return False
        self._hashes.add(record.content_hash)
        return True


class _Duplicate(Exception):
    pass


class CorpusStore:
    """Runtime corpus candidates on a ``hydra.core.eventlog`` log: ``corpus.jsonl`` under the runtime
    directory, or the PostgreSQL stream ``runtime/corpus.jsonl`` shared by every node. ``append_once``
    checks the content hash while the stream is locked, so a record replayed by two nodes is kept once."""

    STREAM = "runtime/corpus.jsonl"

    def __init__(self, path: str | Path = runtime_path("corpus.jsonl"), log=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log if log is not None else FileLog(self.path, self.STREAM)
        self._lock = threading.Lock()
        self._seen = 0
        self._hashes: set[str] = set()

    def _catch_up(self) -> None:
        for seq, line in self.log.read(self._seen):
            self._seen = seq
            content_hash = json.loads(line).get("content_hash")
            if content_hash:
                self._hashes.add(content_hash)

    def append(self, record: CorpusRecord) -> CorpusRecord:
        self.log.append(record.model_dump_json())
        return record

    def contains_hash(self, content_hash: str) -> bool:
        with self._lock:
            self._catch_up()
            return content_hash in self._hashes

    def append_once(self, record: CorpusRecord) -> bool:
        if not record.content_hash:
            raise ValueError("Corpus record must have content_hash")

        def build(seq: int, last: str | None) -> str:
            self._catch_up()  # the stream is locked: every record written before this one
            if record.content_hash in self._hashes:
                raise _Duplicate
            return record.model_dump_json()

        with self._lock:
            try:
                self.log.append(build)
            except _Duplicate:
                return False
            self._catch_up()
            return True
