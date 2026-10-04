# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.evaluate_decision_corpus import load


def test_loader_preserves_frozen_splits():
    calibration = load(__import__("pathlib").Path("data/decision-corpus-v3/calibration.jsonl"))
    test = load(__import__("pathlib").Path("data/decision-corpus-v3/test.jsonl"))
    assert len(calibration) == 200 and len(test) == 1000
    assert not {row["id"] for row in calibration} & {row["id"] for row in test}
    assert all(row["training_allowed"] is False for row in calibration + test)
