# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.ledger.runtime_anchor import ANCHOR, BROKEN, anchor_runtime_chains
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord


def _stores(tmp_path):
    return JsonlEventStore(tmp_path / "events.jsonl"), ProvenanceLedger(tmp_path / "provenance.jsonl")


def _anchors(ledger, kind=ANCHOR):
    return [e for e in ledger.events() if e.event_type == kind]


async def test_heads_are_anchored_once_per_change(runtime, tmp_path):
    events, provenance = _stores(tmp_path)
    events.append(event_type="hydra.test", aggregate_id=uuid4(), producer="test", trace_id="t", payload={"a": 1})
    first = anchor_runtime_chains(runtime.ledger, events, provenance)
    assert first["events"] == {"records": 1, "head": events.head}
    assert anchor_runtime_chains(runtime.ledger, events, provenance) is None  # unchanged -> no new entry
    provenance.append(ProvenanceRecord(task_id=uuid4(), trace_id="t", action="a", inputs={}, outputs={}))
    second = anchor_runtime_chains(runtime.ledger, events, provenance)
    assert second["provenance"]["head"] == provenance.head
    assert len(_anchors(runtime.ledger)) == 2 and runtime.ledger.verify().ok


async def test_tampered_runtime_chain_is_recorded_not_anchored(runtime, tmp_path):
    events, provenance = _stores(tmp_path)
    events.append(event_type="hydra.test", aggregate_id=uuid4(), producer="test", trace_id="t", payload={"a": 1})
    anchor_runtime_chains(runtime.ledger, events, provenance)
    line = json.loads(events.path.read_text(encoding="utf-8"))
    line["payload"]["a"] = 2  # rewrite history
    events.path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    result = anchor_runtime_chains(runtime.ledger, events, provenance)
    assert result["event_type"] == BROKEN and "payload hash mismatch" in result["errors"]["events"]
    assert anchor_runtime_chains(runtime.ledger, events, provenance) is None  # recorded once
    assert len(_anchors(runtime.ledger)) == 1 and len(_anchors(runtime.ledger, BROKEN)) == 1


def test_gateway_anchors_runtime_chains_on_shutdown(settings):
    app = create_app(settings)
    with TestClient(app):
        pass
    assert _anchors(app.state.runtime.ledger)
