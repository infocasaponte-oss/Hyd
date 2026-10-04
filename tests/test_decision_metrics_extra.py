# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.decision_benchmark import cases, identity


def test_benchmark_identity_and_no_training_leakage():
    rows = cases()
    assert len(rows) == 56
    assert identity()
    assert all(row["split"] in {"calibration", "test", "ood"} for row in rows)
