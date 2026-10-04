# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord


def test_provenance_record_gets_hash(tmp_path):
    ledger = ProvenanceLedger(tmp_path / "provenance.jsonl")
    record = ledger.append(
        ProvenanceRecord(
            task_id=uuid4(),
            trace_id="trace",
            action="patch.verified",
            inputs={"patch_sha256": "abc"},
            outputs={"tests_passed": True},
        )
    )
    assert len(record.record_hash) == 64
    assert ledger.path.exists()
