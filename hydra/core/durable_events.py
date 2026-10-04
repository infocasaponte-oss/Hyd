# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.eventlog import FileLog
from hydra.core.hash_chain import canonical_hash, lock_for
from hydra.core.runtime_paths import runtime_path


class EventEnvelope(BaseModel):
    schema_version: str = "2"
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    aggregate_id: UUID
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: str
    trace_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    previous_hash: str | None = None
    source_message_id: UUID | None = None
    event_hash: str = ""


class IntegrityReport(BaseModel):
    valid: bool
    records: int
    legacy_records: int = 0
    error: str | None = None


def _event_body(event: EventEnvelope) -> dict[str, Any]:
    return event.model_dump(
        mode="json",
        exclude={"event_hash"},
    )


class _Duplicate(Exception):
    def __init__(self, existing) -> None:
        self.existing = existing


class JsonlEventStore:
    """Append-only event store with a verifiable hash chain.

    The chain lives in a ``hydra.core.eventlog`` log: ``runtime/events.jsonl`` under the runtime
    directory, or the PostgreSQL stream of the same name shared by every node (HYDRA_RUNTIME_BACKEND).
    Sequence, previous hash and the ``source_message_id`` idempotency check are computed while the
    stream is locked, so concurrent writers still produce one valid chain without duplicates."""

    STREAM = "runtime/events.jsonl"

    def __init__(self, path: str | Path = runtime_path("events.jsonl"), log=None):
        self.path = Path(path)
        self.log = log if log is not None else FileLog(self.path, self.STREAM)
        self._lock = lock_for(self.path)
        self._seen = 0
        self._sequence = 0
        self._last_hash: str | None = None
        self._by_source: dict[UUID, EventEnvelope] = {}
        with self._lock:
            self._catch_up()

    def _catch_up(self) -> None:
        for seq, line in self.log.read(self._seen):
            event = EventEnvelope.model_validate_json(line)
            self._seen = seq
            self._sequence = max(self._sequence, event.sequence)
            self._last_hash = event.event_hash or self._last_hash
            if event.source_message_id is not None:
                self._by_source.setdefault(event.source_message_id, event)

    def _events(self):
        for _, line in self.log.read():
            yield EventEnvelope.model_validate_json(line)

    @property
    def head(self) -> str | None:
        """Hash of the last chained event (anchored in the signed platform ledger)."""
        with self._lock:
            self._catch_up()
            return self._last_hash

    def append(
        self,
        *,
        event_type: str,
        aggregate_id: UUID,
        producer: str,
        trace_id: str,
        payload: dict[str, Any] | None = None,
        source_message_id: UUID | None = None,
    ) -> EventEnvelope:
        body = payload or {}

        def build(seq: int, last: str | None) -> str:
            self._catch_up()  # the stream is locked: this is everything written before this entry
            if source_message_id is not None and source_message_id in self._by_source:
                raise _Duplicate(self._by_source[source_message_id])
            event = EventEnvelope(
                event_type=event_type,
                aggregate_id=aggregate_id,
                sequence=self._sequence + 1,
                producer=producer,
                trace_id=trace_id,
                payload=body,
                payload_hash=canonical_hash(body),
                previous_hash=self._last_hash,
                source_message_id=source_message_id,
            )
            event.event_hash = canonical_hash(_event_body(event))
            return event.model_dump_json()

        with self._lock:
            try:
                _, text = self.log.append(build)
            except _Duplicate as duplicate:
                return duplicate.existing
            self._catch_up()
            return EventEnvelope.model_validate_json(text)

    def by_source_message_id(self, source_message_id: UUID) -> EventEnvelope | None:
        with self._lock:
            self._catch_up()
            return self._by_source.get(source_message_id)

    def for_aggregate(self, aggregate_id: UUID) -> list[EventEnvelope]:
        return [event for event in self._events() if event.aggregate_id == aggregate_id]

    def verify_integrity(self) -> IntegrityReport:
        previous_hash = None
        previous_sequence = 0
        records = 0
        legacy = 0
        # one log entry per chained record; "line" is its position in the chain
        for line_number, line in self.log.read():
            try:
                event = EventEnvelope.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001
                return IntegrityReport(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: invalid event: {exc}",
                )
            records += 1
            if canonical_hash(event.payload) != event.payload_hash:
                return IntegrityReport(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: payload hash mismatch",
                )
            if event.sequence <= previous_sequence:
                return IntegrityReport(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: non-monotonic sequence",
                )
            if not event.event_hash:
                legacy += 1
                previous_sequence = event.sequence
                previous_hash = None
                continue
            if event.previous_hash != previous_hash:
                return IntegrityReport(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: previous hash mismatch",
                )
            if canonical_hash(_event_body(event)) != event.event_hash:
                return IntegrityReport(
                    valid=False,
                    records=records,
                    legacy_records=legacy,
                    error=f"line {line_number}: event hash mismatch",
                )
            previous_sequence = event.sequence
            previous_hash = event.event_hash
        return IntegrityReport(valid=True, records=records, legacy_records=legacy)
