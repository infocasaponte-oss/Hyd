# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.train_decision_v2 import train


def test_decision_v2_trains_all_contract_labels(tmp_path):
    result = train(output=tmp_path / "model")
    assert result["manifest"]["format"] == "hydra-decision-v2/1"
    assert set(result["manifest"]["labels"]) == {
        "chat", "coding", "reasoning", "research", "vision", "tool_use",
        "security", "privacy", "abstain", "high_risk_review"}
    assert (tmp_path / "model" / "classifier.json").is_file()
