# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest

from hyd_calibrator.contributed_lopo import admitted_marks, validate_contributions
from hyd_calibrator.corpus import validate
from tests.test_hybrid_lopo_admission import corpus


def contributions():
    rows = corpus()
    for row in rows:
        row.update(consent=True, consent_text="declared permission for training and evaluation",
                   rights={"license": "contributed-with-consent", "declared_by": "contributor"},
                   flags=["suspect_template"])
    return rows


def test_numbered_template_variants_are_retained_verbatim():
    rows = contributions()
    rows[0]["text"] = "17. " + rows[0]["text"]
    rows[0]["text_sha256"] = hashlib.sha256(rows[0]["text"].encode()).hexdigest()
    before = rows[0]["text"]
    folds = validate_contributions(rows)
    assert len(folds) == 3 and len(rows) == 60
    assert rows[0]["text"] == before


def test_contributor_consent_is_explicit_not_invented():
    rows = contributions()
    rows[0]["consent"] = False
    with pytest.raises(ValueError, match="declaration and consent"):
        validate_contributions(rows)


def test_calibrator_variant_flag_does_not_invalidate_question(tmp_path):
    text = "17. Cambia o importe de 20 a 30 euros"
    row = {"text": text, "expected": "tool_use", "meta": {"consent": True, "real": True, "suspect_template": True},
           "rights": {"license": "owner-declared", "verified": True}}
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(row), encoding="utf-8")
    rows, report = validate(source)
    assert report["n_errors"] == 0 and rows[0]["text"] == text
    assert rows[0]["meta"]["suspect_template"] is True


def test_annotation_sources_preserved_and_absent_records_counted():
    rows = contributions()
    record = next(r for r in rows if r["expected"] == "abstain")
    mark = {"id": record["id"], "text": record["text"], "text_sha256": record["text_sha256"],
            "person": record["person"], "kind": "dangerous", "source": "human_reconfirmed"}
    outside = dict(mark, id="not-in-corpus")
    kept, count = admitted_marks(rows, [mark, outside])
    assert kept == [mark] and count == 1


def test_annotation_owner_and_text_must_match():
    rows = contributions()
    record = next(r for r in rows if r["expected"] == "abstain")
    mark = {"id": record["id"], "text": record["text"], "text_sha256": record["text_sha256"],
            "person": "wrong", "kind": "dangerous", "source": "human_original"}
    with pytest.raises(ValueError, match="does not match"):
        admitted_marks(rows, [mark])
