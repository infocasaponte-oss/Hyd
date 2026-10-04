# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord
from hydra.runtime.replay_integrity import verify_replay_sources


def test_replay_sources_require_valid_chains(tmp_path):
    events = JsonlEventStore(tmp_path / "events.jsonl")
    provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")
    task_id = uuid4()
    events.append(
        event_type="hydra.test",
        aggregate_id=task_id,
        producer="test",
        trace_id="trace",
    )
    provenance.append(
        ProvenanceRecord(
            task_id=task_id,
            trace_id="trace",
            action="test",
        )
    )
    report = verify_replay_sources(events, provenance)
    assert report.valid is True
    assert report.event_records == 1
    assert report.provenance_records == 1
