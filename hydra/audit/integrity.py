# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Integrity of the event and provenance chains a replay relies on."""
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.durable_events import JsonlEventStore
from hydra.provenance.ledger import ProvenanceLedger


@dataclass(frozen=True)
class ReplayIntegrity:
    valid: bool
    event_records: int
    provenance_records: int
    error: str | None = None


def verify_replay_sources(
    events: JsonlEventStore,
    provenance: ProvenanceLedger,
) -> ReplayIntegrity:
    event_report = events.verify_integrity()
    if not event_report.valid:
        return ReplayIntegrity(
            valid=False,
            event_records=event_report.records,
            provenance_records=0,
            error=f"events: {event_report.error}",
        )
    provenance_report = provenance.verify_integrity()
    if not provenance_report.valid:
        return ReplayIntegrity(
            valid=False,
            event_records=event_report.records,
            provenance_records=provenance_report.records,
            error=f"provenance: {provenance_report.error}",
        )
    if event_report.legacy_records or provenance_report.legacy_records:
        return ReplayIntegrity(
            valid=False,
            event_records=event_report.records,
            provenance_records=provenance_report.records,
            error="legacy unhashed records present",
        )
    return ReplayIntegrity(
        valid=True,
        event_records=event_report.records,
        provenance_records=provenance_report.records,
    )
