# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest

from hyd_calibrator.corpus_readiness import readiness


def fixture(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    content = evidence / "review.txt"
    content.write_text("Technical test fixture, not a real legal review.")
    report = {"format": "hyd-corpus-census/1", "complete": True, "token_count_complete": True, "snapshot_manifest_sha256": "a" * 64,
              "groups": [{"bucket": "candidates", "source": "fixture", "source_revision": "b" * 40,
                          "license_declaration": "CC0-1.0", "content_tokens": 12,
                          "category_declaration": "test", "language_declaration": "es"}]}
    review = {"format": "hyd-source-rights-review/1", "snapshot_manifest_sha256": "a" * 64,
              "sources": [{"source": "fixture", "revision": "b" * 40, "license_declaration": "CC0-1.0",
                           "review_status": "reviewed", "reviewer": {"id": "test-fixture", "kind": "human"},
                           "lawful_access": "reviewed", "rights_basis": "explicit-license",
                           "attribution_complete": "reviewed", "tdm_reservations": "respected-reviewed",
                           "personal_data_review": "reviewed", "evidence": [{"path": "review.txt",
                               "sha256": hashlib.sha256(content.read_bytes()).hexdigest()}]}],
              "dataset_review": {"diversity_reviewed": True, "language_verified": True,
                                 "benchmark_decontamination_verified": True,
                                 "evidence": [{"path": "review.txt", "sha256": hashlib.sha256(content.read_bytes()).hexdigest()}],
                                 "reviewer": {"id": "test-fixture", "kind": "human"}}}
    census_file, rights_file = tmp_path / "census.json", tmp_path / "rights.json"
    census_file.write_text(json.dumps(report))
    rights_file.write_text(json.dumps(review))
    return census_file, rights_file, evidence, review


def test_evidence_bound_diagnostic_never_grants_training_authority(tmp_path):
    census, rights, evidence, _ = fixture(tmp_path)
    report = readiness(census, rights, evidence, tmp_path / "out.json")
    assert report["ready_for_dataset_build"] is True and report["training_allowed"] is False
    assert report["candidate_balance_by_tokens"]["source"][0]["share"] == 1


def test_pending_source_and_dataset_review_fail_closed(tmp_path):
    census, rights, evidence, data = fixture(tmp_path)
    data["sources"][0]["review_status"] = "pending"
    data["dataset_review"] = {}
    rights.write_text(json.dumps(data))
    report = readiness(census, rights, evidence, tmp_path / "out.json")
    assert report["ready_for_dataset_build"] is False
    assert any("human_rights_review_missing" in b["reasons"] for b in report["blockers"])


def test_changed_evidence_and_escaping_paths_are_rejected(tmp_path):
    census, rights, evidence, data = fixture(tmp_path)
    data["sources"][0]["evidence"][0]["path"] = "../outside.txt"
    rights.write_text(json.dumps(data))
    report = readiness(census, rights, evidence, tmp_path / "out.json")
    assert any("source_evidence_invalid" in b["reasons"] for b in report["blockers"])


def test_review_for_other_snapshot_is_rejected(tmp_path):
    census, rights, evidence, data = fixture(tmp_path)
    data["snapshot_manifest_sha256"] = "c" * 64
    rights.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="exact snapshot"):
        readiness(census, rights, evidence, tmp_path / "out.json")


def test_unmeasured_records_cannot_pass_even_with_reviewed_rights(tmp_path):
    census, rights, evidence, _ = fixture(tmp_path)
    data = json.loads(census.read_text())
    data["token_count_complete"] = False
    census.write_text(json.dumps(data))
    report = readiness(census, rights, evidence, tmp_path / "out.json")
    assert report["ready_for_dataset_build"] is False and report["token_count_complete"] is False
