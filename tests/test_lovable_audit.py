# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from copy import deepcopy
import hashlib

from hyd_calibrator.lovable_audit import audit_rows


def fixture():
    digest = hashlib.sha256(b"original text").hexdigest()
    records = [{"id": "record", "question": "original text", "text_sha256": digest,
                "expected_label": "abstain", "consent": True, "consent_text": "declared consent",
                "account_pseudonym": "owner", "rights_verified": False}]
    annotations = [{"annotation_id": "ann", "record_id": "record", "record_sha256": digest,
                    "ai_correction_suspected": True, "human_original_kind": None,
                    "human_review_status": "pending", "selected_for_evaluation": False}]
    queue = [{"id": "queue", "annotation_id": "ann", "record_id": "record", "owner_pseudonym": "owner",
              "status": "pending", "confirmed_kind": None, "confirmed_at": None, "confirmed_by_pseudonym": None}]
    return records, annotations, queue


def test_pending_export_preserves_no_approval():
    rows = fixture()
    before = deepcopy(rows)
    report = audit_rows(*rows)
    assert report["structurally_valid"]
    assert report["counts"]["rights_verified"] == 0
    assert not report["training_approved"]
    assert not report["human_reference_approved"]
    assert rows == before


def test_wrong_text_and_reference_fail():
    records, annotations, queue = fixture()
    records[0]["question"] = "corrected text"
    annotations[0]["record_id"] = "missing"
    report = audit_rows(records, annotations, queue)
    assert not report["structurally_valid"]
    assert report["structural_errors"]["verbatim_text_hash_mismatch"] == 1


def test_foreign_reconfirmation_and_pending_selection_fail():
    records, annotations, queue = fixture()
    annotations[0]["selected_for_evaluation"] = True
    queue[0].update(status="reviewed", confirmed_kind="dangerous", confirmed_at="2026-10-05T00:00:00Z",
                    confirmed_by_pseudonym="other")
    errors = audit_rows(records, annotations, queue)["structural_errors"]
    assert errors["reviewed_confirmation_incomplete_or_foreign"] == 1
    assert errors["pending_annotation_selected"] == 1


def test_reconfirmation_is_not_automatic_selection():
    records, annotations, queue = fixture()
    queue[0].update(status="reviewed", confirmed_kind="dangerous", confirmed_at="2026-10-05T00:00:00Z",
                    confirmed_by_pseudonym="owner")
    report = audit_rows(records, annotations, queue)
    assert report["structurally_valid"]
    assert report["counts"]["selected_annotations"] == 0
    assert not report["human_reference_approved"]


def test_missing_queue_entry_and_duplicate_records_fail():
    records, annotations, queue = fixture()
    records.append(deepcopy(records[0]))
    report = audit_rows(records, annotations, [])
    assert report["structural_errors"]["record_id_invalid_or_duplicate"] == 1
    assert report["structural_errors"]["queue_does_not_cover_suspected_annotations"] == 1
