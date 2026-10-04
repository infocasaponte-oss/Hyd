# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord


def test_event_store_detects_payload_tampering(tmp_path):
    path = tmp_path / "events.jsonl"
    store = JsonlEventStore(path)
    store.append(
        event_type="hydra.test",
        aggregate_id=uuid4(),
        producer="test",
        trace_id="trace",
        payload={"value": 1},
    )
    assert store.verify_integrity().valid is True

    line = json.loads(path.read_text())
    line["payload"]["value"] = 2
    path.write_text(json.dumps(line) + "\n")
    report = JsonlEventStore(path).verify_integrity()
    assert report.valid is False
    assert "payload hash mismatch" in (report.error or "")


def test_event_store_detects_chain_break(tmp_path):
    path = tmp_path / "events.jsonl"
    store = JsonlEventStore(path)
    aggregate = uuid4()
    store.append(
        event_type="hydra.one",
        aggregate_id=aggregate,
        producer="test",
        trace_id="trace",
    )
    store.append(
        event_type="hydra.two",
        aggregate_id=aggregate,
        producer="test",
        trace_id="trace",
    )
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    lines[1]["previous_hash"] = "0" * 64
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert JsonlEventStore(path).verify_integrity().valid is False


def test_provenance_detects_record_tampering(tmp_path):
    path = tmp_path / "provenance.jsonl"
    ledger = ProvenanceLedger(path)
    ledger.append(
        ProvenanceRecord(
            task_id=uuid4(),
            trace_id="trace",
            action="test",
            inputs={"a": 1},
            outputs={"b": 2},
        )
    )
    assert ledger.verify_integrity().valid is True

    line = json.loads(path.read_text())
    line["outputs"]["b"] = 999
    path.write_text(json.dumps(line) + "\n")
    assert ProvenanceLedger(path).verify_integrity().valid is False
