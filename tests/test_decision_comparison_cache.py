# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_compare import cached_baseline


def test_cache_requires_completed_matching_experiment(tmp_path):
    path = tmp_path / "cache.json"
    row = {"id": "fixture", "text": "texto sintético", "text_sha256": "fixture-digest",
           "expected": "coding", "group_id": "fixture-scenario"}
    predicted = {**row, "selected": "coding", "probabilities": {k: float(k == "coding") for k in CRITERIA}}
    evidence = {"format": "hyd-kev-paired/1", "complete": True, "kev_checkpoint_files": {"head.pt": "fixture"},
                "kev_calibration_sha256": "cal", "test_sha256": "test", "kev_rows": [predicted]}
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert cached_baseline(path, {"head.pt": "fixture"}, "cal", "test", [row])["fixture"]["selected"] == "coding"
    for key, value in [("complete", False), ("kev_calibration_sha256", "different"),
                       ("kev_checkpoint_files", {}), ("test_sha256", "different")]:
        path.write_text(json.dumps({**evidence, key: value}), encoding="utf-8")
        with pytest.raises(ValueError, match="another experiment"):
            cached_baseline(path, {"head.pt": "fixture"}, "cal", "test", [row])
    path.write_text(json.dumps({**evidence, "kev_rows": [{**predicted, "text_sha256": "different"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="content"):
        cached_baseline(path, {"head.pt": "fixture"}, "cal", "test", [row])
