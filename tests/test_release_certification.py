# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from pathlib import Path

from scripts import check_instruction_certification as certification


def test_fresh_run_cannot_promote_incomplete_evidence_or_forged_review_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(certification, "candidate_hash", lambda _: "candidate")
    corpus = tmp_path / "data/external-evaluation-v2"
    corpus.mkdir(parents=True)
    (corpus / "cases.json").write_text(json.dumps([{"id": 1}]))
    (corpus / "manifest.json").write_text(json.dumps({
        "unique_cases": 100, "cases_sha256": "test", "duplicate_groups": []
    }))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "external-evaluation-v5-reviews.json").write_text(json.dumps({
        "unique_reviewed": 100, "unique_correct": 100,
        "artifact_sha256": "candidate", "dataset_sha256": "test",
        "human_authorship_attested": True, "cases": {}
    }))
    evidence = Path("docs/evidence/fresh-run")
    (tmp_path / evidence).mkdir(parents=True)
    report = certification.check(tmp_path, evidence, Path("missing-soak.json"))
    assert report["human_reviewed"] == 0
    assert not report["gates"]["human_review_complete"]
    assert not report["gates"]["fresh_process_complete"]
    assert not report["eligible_for_manual_promotion"]
    assert report["approved"] is False
