# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.runtime_evidence import RuntimeEvidenceStore


def test_runtime_evidence_hashes_outputs(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    record = store.append(
        trace_id="trace",
        capability="reasoning.general",
        primary_variant_id="active",
        primary_output="same",
        shadow_variant_id="shadow",
        shadow_output="same",
    )
    assert record.exact_agreement is True
    assert len(record.primary_output_sha256) == 64
    assert record.primary_output_sha256 == record.shadow_output_sha256


def test_phase_aggregates_are_incremental_and_ignore_partial_lines(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.jsonl")
    for i in range(3):
        store.append(trace_id=f"t{i}", capability="c", primary_variant_id="a", primary_output="x",
                     canary_variant_id="v", canary_error=False, canary_latency_ms=10.0 * (i + 1))
    assert store.canary_evidence("v").requests == 3
    offset = store._tallies[("canary", "v", 0)].offset
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write('{"canary_variant_id": "v", "canary_error": true')  # a writer is mid-line
    assert store.canary_evidence("v").requests == 3  # the partial line is not consumed
    assert store._tallies[("canary", "v", 0)].offset == offset
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write("}\n")
    measured = store.canary_evidence("v")
    assert measured.requests == 4 and measured.error_rate == 0.25 and measured.p95_latency_ms == 30.0
