# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import numpy as np
import pytest

from hydra.hyd import encoder_study
from hydra.hyd.hybrid_lopo import LABELS


def _corpus(tmp_path):
    rows = []
    for person in ("p-a", "p-b", "p-c"):
        for label in sorted(LABELS):
            for k in range(30):
                family = f"{person}-{label}-{k}"
                for variant in range(2):  # two variants per family must stay together
                    text = f"{person} pide {label} caso {k} variante {variant}"
                    rows.append({"id": f"{family}-{variant}", "text": text, "expected": label, "person": person,
                                 "family": family, "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
    path = tmp_path / "corpus.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_partitions_are_disjoint_by_family_and_dev_never_touches_the_held_out_person(tmp_path):
    rows, splits = encoder_study.load(_corpus(tmp_path))
    families = np.array([r["family"] for r in rows])
    persons = np.array([r["person"] for r in rows])
    assert sorted(splits) == ["p-a", "p-b", "p-c"]
    for held, s in splits.items():
        masks = [s[k] for k in ("fit", "dev", "cal", "test")]
        assert (sum(m.astype(int) for m in masks) == 1).all()  # every row in exactly one partition
        for i, left in enumerate(masks):
            for right in masks[i + 1:]:
                assert not set(families[left]) & set(families[right])
        assert set(persons[s["test"]]) == {held}
        assert held not in set(persons[s["dev"]]) | set(persons[s["cal"]]) | set(persons[s["fit"]])
        assert 0.1 < s["dev"].sum() / (~s["test"]).sum() < 0.3


def test_temperature_is_fitted_on_given_logits_and_keeps_argmax():
    classes = np.array(["a", "b"])
    logits = np.array([[4.0, 0.0], [0.0, 4.0], [3.0, 0.0], [0.0, 1.0]])
    y = np.array(["a", "b", "b", "b"])
    t = encoder_study.temperature(logits, y, classes)
    assert 0.3 <= t <= 3
    p = encoder_study.softmax_t(logits, t)
    assert (p.argmax(1) == logits.argmax(1)).all()


def test_unknown_mode_is_rejected():
    with pytest.raises(SystemExit):
        encoder_study.main(["predict", "--corpus", "x", "--out", "y"])
