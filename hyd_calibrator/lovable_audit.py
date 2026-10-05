# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Read-only audit of the Lovable export; no relabeling or inferred approval."""

from collections import Counter
import csv
import hashlib
import io
import json
import zipfile

from hyd_calibrator.export_bundle import _unique_object, verify_bundle

LABELS = {"chat", "research", "reasoning", "coding", "abstain", "privacy",
          "security", "vision", "tool_use", "high_risk_review"}


def audit_rows(records, annotations, queue):
    errors = Counter()
    by_record, by_annotation = {}, {}
    classes = Counter()
    for row in records:
        key = row.get("id")
        if not isinstance(key, str) or not key or key in by_record:
            errors["record_id_invalid_or_duplicate"] += 1
        by_record[key] = row
        text = row.get("question")
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row.get("text_sha256"):
            errors["verbatim_text_hash_mismatch"] += 1
        if row.get("expected_label") not in LABELS:
            errors["unknown_label"] += 1
        classes[row.get("expected_label")] += 1
        if row.get("consent") is not True or not str(row.get("consent_text") or "").strip():
            errors["missing_consent_evidence"] += 1
    for row in annotations:
        key = row.get("annotation_id")
        if not isinstance(key, str) or not key or key in by_annotation:
            errors["annotation_id_invalid_or_duplicate"] += 1
        by_annotation[key] = row
        record = by_record.get(row.get("record_id"))
        if record is None or record.get("expected_label") != "abstain":
            errors["annotation_record_missing_or_not_abstain"] += 1
        elif row.get("record_sha256") != record.get("text_sha256"):
            errors["annotation_text_hash_mismatch"] += 1
        if row.get("human_review_status") == "pending" and row.get("selected_for_evaluation") is not False:
            errors["pending_annotation_selected"] += 1
        if row.get("ai_correction_suspected") is True and row.get("human_original_kind") is not None:
            errors["suspected_correction_asserts_original"] += 1
    queue_ids, queue_annotations = set(), set()
    for row in queue:
        key = row.get("id")
        if not isinstance(key, str) or not key or key in queue_ids:
            errors["queue_id_invalid_or_duplicate"] += 1
        queue_ids.add(key)
        ann_id = row.get("annotation_id")
        if ann_id in queue_annotations:
            errors["queue_duplicate_annotation"] += 1
        queue_annotations.add(ann_id)
        annotation = by_annotation.get(ann_id)
        record = by_record.get(row.get("record_id"))
        if not annotation or annotation.get("record_id") != row.get("record_id"):
            errors["queue_annotation_reference_mismatch"] += 1
        if not record or row.get("owner_pseudonym") != record.get("account_pseudonym"):
            errors["queue_owner_mismatch"] += 1
        if row.get("status") == "reviewed":
            if (row.get("confirmed_by_pseudonym") != row.get("owner_pseudonym")
                    or not row.get("confirmed_at")
                    or row.get("confirmed_kind") not in {"dangerous", "missing_context", "unsure"}):
                errors["reviewed_confirmation_incomplete_or_foreign"] += 1
        elif row.get("status") != "pending" or any(row.get(k) is not None for k in
                ("confirmed_kind", "confirmed_at", "confirmed_by_pseudonym")):
            errors["pending_confirmation_inconsistent"] += 1
    suspected = {x.get("annotation_id") for x in annotations if x.get("ai_correction_suspected") is True}
    if queue_annotations != suspected:
        errors["queue_does_not_cover_suspected_annotations"] += 1
    return {"structural_errors": dict(errors), "structurally_valid": not errors,
            "counts": {"records": len(records), "annotations": len(annotations), "queue": len(queue),
                       "by_class": dict(classes), "queue_status": dict(Counter(x.get("status") for x in queue)),
                       "consent_true": sum(x.get("consent") is True for x in records),
                       "rights_verified": sum(x.get("rights_verified") is True for x in records),
                       "provenance_declared": sum(bool(x.get("provenance_declared")) for x in records),
                       "independent_person_verified": sum(x.get("independent_person_verified") is True for x in records),
                       "selected_annotations": sum(x.get("selected_for_evaluation") is True for x in annotations),
                       "pending_annotations": sum(x.get("human_review_status") == "pending" for x in annotations),
                       "filtered_training_flag": sum(x.get("included_in_filtered_training") is True for x in records)},
            "training_approved": False, "human_reference_approved": False,
            "notes": ["Consent does not establish provenance or rights.",
                      "Queue reviewed status is exported evidence, not independent proof of human identity.",
                      "Reconfirmations remain separate from annotation selection; no targets are inferred."]}


def audit_lovable_bundle(source, expected_sha256):
    integrity = verify_bundle(source, expected_sha256)
    with zipfile.ZipFile(source) as archive:
        def read_json(name):
            return json.loads(archive.read(name).decode("utf-8-sig"), object_pairs_hook=_unique_object)
        records = read_json("data/hyd_records_full.json")
        annotations = read_json("annotations/abstain_annotations.json")
        queue = read_json("annotations/reconfirm_queue.json")
        manifest = read_json("MANIFEST.json")
        if any(not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
               for rows in (records, annotations, queue)):
            raise ValueError("export tables must contain object rows")
        report = audit_rows(records, annotations, queue)
        expected = manifest.get("counts", {})
        bindings = {"hyd_records": "records", "hyd_abstain_annotations": "annotations",
                    "hyd_abstain_reconfirm_queue": "queue", "by_class": "by_class",
                    "reconfirm_by_status": "queue_status", "included_filtered_training": "filtered_training_flag"}
        for key, measured in bindings.items():
            if expected.get(key) != report["counts"][measured]:
                report["structural_errors"]["manifest_count_mismatch_" + key] = 1
        csv_rows = list(csv.DictReader(io.StringIO(archive.read("data/hyd_records_full.csv").decode("utf-8-sig"))))
        json_pairs = Counter((r.get("id"), r.get("question")) for r in records)
        csv_pairs = Counter((r.get("id"), r.get("question")) for r in csv_rows)
        if csv_pairs != json_pairs:
            report["structural_errors"]["csv_json_verbatim_mismatch"] = 1
        report["structurally_valid"] = not report["structural_errors"]
        report["integrity"] = integrity
        return report
