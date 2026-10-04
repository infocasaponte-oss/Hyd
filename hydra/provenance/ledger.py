# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.eventlog import FileLog
from hydra.core.hash_chain import canonical_hash, lock_for
from hydra.core.runtime_paths import runtime_path


class ProvenanceRecord(BaseModel):
    record_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: str
    action: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    previous_hash: str | None = None
    source_message_id: UUID | None = None
    record_hash: str = ""


class ProvenanceIntegrity(BaseModel):
    valid: bool
    records: int
    legacy_records: int = 0
    error: str | None = None


def _record_body(record: ProvenanceRecord) -> dict:
    return record.model_dump(mode="json", exclude={"record_hash"})


class _Duplicate(Exception):
    def __init__(self, existing) -> None:
        self.existing = existing


class ProvenanceLedger:
    """Hash-chained provenance records on a ``hydra.core.eventlog`` log (``runtime/provenance.jsonl``,
    a file or the PostgreSQL stream shared by every node). The previous hash and the idempotency check
    are resolved while the stream is locked."""

    STREAM = "runtime/provenance.jsonl"

    def __init__(self, path: str | Path = runtime_path("provenance.jsonl"), log=None):
        self.path = Path(path)
        self.log = log if log is not None else FileLog(self.path, self.STREAM)
        self._lock = lock_for(self.path)
        self._seen = 0
        self._last_hash: str | None = None
        self._by_source: dict[UUID, ProvenanceRecord] = {}
        with self._lock:
            self._catch_up()

    def _catch_up(self) -> None:
        for seq, line in self.log.read(self._seen):
            record = ProvenanceRecord.model_validate_json(line)
            self._seen = seq
            self._last_hash = record.record_hash or self._last_hash
            if record.source_message_id is not None:
                self._by_source.setdefault(record.source_message_id, record)

    @property
    def head(self) -> str | None:
        """Hash of the last chained record (anchored in the signed platform ledger)."""
        with self._lock:
            self._catch_up()
            return self._last_hash

    def append(self, record: ProvenanceRecord) -> ProvenanceRecord:
        def build(seq: int, last: str | None) -> str:
            self._catch_up()
            if record.source_message_id is not None and record.source_message_id in self._by_source:
                raise _Duplicate(self._by_source[record.source_message_id])
            chained = record.model_copy(update={"previous_hash": self._last_hash, "record_hash": ""})
            chained.record_hash = canonical_hash(_record_body(chained))
            return chained.model_dump_json()

        with self._lock:
            try:
                _, text = self.log.append(build)
            except _Duplicate as duplicate:
                return duplicate.existing
            self._catch_up()
            stored = ProvenanceRecord.model_validate_json(text)
            record.previous_hash, record.record_hash = stored.previous_hash, stored.record_hash
            return record

    def by_source_message_id(
        self, source_message_id: UUID
    ) -> ProvenanceRecord | None:
        with self._lock:
            self._catch_up()
            return self._by_source.get(source_message_id)

    def verify_integrity(self) -> ProvenanceIntegrity:
        previous_hash = None
        records = 0
        legacy = 0
        # one log entry per chained record; "line" is its position in the chain
        for line_number, line in self.log.read():
            try:
                record = ProvenanceRecord.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001
                return ProvenanceIntegrity(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: invalid record: {exc}",
                )
            records += 1
            if not record.record_hash:
                legacy += 1
                previous_hash = None
                continue
            if record.previous_hash != previous_hash:
                return ProvenanceIntegrity(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: previous hash mismatch",
                )
            if canonical_hash(_record_body(record)) != record.record_hash:
                return ProvenanceIntegrity(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: record hash mismatch",
                )
            previous_hash = record.record_hash
        return ProvenanceIntegrity(
            valid=True,
            records=records,
            legacy_records=legacy,
        )
