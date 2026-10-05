# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib

import pytest

from hydra.hyd.hybrid_lopo import LABELS, main, validate_folds


def corpus():
    rows = []
    for person in ("a", "b", "c"):
        for label in sorted(LABELS):
            for is_cal in (False, True):
                n = 0
                while True:
                    family = f"{person}-{label}-{is_cal}-{n}"
                    if (int(hashlib.sha256(family.encode()).hexdigest()[:8], 16) % 5 == 0) == is_cal:
                        break
                    n += 1
                text = f"fixture {family}"
                rows.append(dict(id=family, family=family, person=person, expected=label,
                                 text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()))
    return rows


def test_three_nonoverlapping_folds():
    rows = corpus()
    folds = validate_folds(rows)
    assert len(folds) == 3
    for held, (fit, cal, test) in folds.items():
        assert fit.sum() == 20 and cal.sum() == 20 and test.sum() == 20
        assert {rows[i]["person"] for i in range(len(rows)) if test[i]} == {held}


def test_cross_person_family_is_rejected():
    rows = corpus()
    rows[20]["family"] = rows[0]["family"]
    with pytest.raises(ValueError, match="family leak"):
        validate_folds(rows)


def test_normalized_duplicate_is_rejected():
    rows = corpus()
    rows[20]["text"] = rows[0]["text"].upper()
    rows[20]["text_sha256"] = hashlib.sha256(rows[20]["text"].encode()).hexdigest()
    with pytest.raises(ValueError, match="duplicate normalized"):
        validate_folds(rows)


@pytest.mark.parametrize("field", ["person", "family", "text_sha256"])
def test_missing_metadata_and_wrong_hash_rejected(field):
    rows = corpus()
    del rows[0][field]
    with pytest.raises(ValueError):
        validate_folds(rows)


def test_missing_calibration_class_rejected():
    rows = [r for r in corpus() if not (r["expected"] == "vision" and "True" in r["family"])]
    with pytest.raises(ValueError, match="ten classes"):
        validate_folds(rows)


def test_invalid_revision_rejected_before_encoder_or_corpus_read(tmp_path):
    with pytest.raises(ValueError, match="exact 40-character"):
        main(["--corpus", str(tmp_path / "missing.jsonl"), "--out", str(tmp_path / "out"),
              "--encoder-revision", "main"])
