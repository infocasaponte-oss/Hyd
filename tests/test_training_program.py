# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest
from hydra.training.program import content_key, release_gate


def test_gate_fails_closed_without_human_test():
    gate = release_gate({"objective_accuracy": 1.0})
    assert not gate["eligible"]
    assert "independent_test" in gate["failures"]
    assert gate["approved"] is False


def test_reject_boolean_metric_and_empty_answer():
    assert "objective_accuracy" in release_gate({"objective_accuracy": True})["failures"]
    assert "objective_accuracy" in release_gate({"objective_accuracy": float("nan")})["failures"]
    with pytest.raises(ValueError):
        content_key({"messages": [{"role": "assistant", "content": ""}]})
    with pytest.raises(ValueError):
        content_key({"messages": [{"role": "assistant", "content": "precisi\u00c3\u00b3n"}]})
