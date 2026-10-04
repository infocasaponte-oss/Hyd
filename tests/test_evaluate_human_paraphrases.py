# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.human_paraphrase_eval import HUMAN_CASES


def test_human_set_has_ten_balanced_families():
    assert set(HUMAN_CASES) == {"chat", "coding", "reasoning", "research", "vision", "tool_use",
                                "security", "privacy", "abstain", "high_risk_review"}
    assert all(len(prompts) == 10 for prompts in HUMAN_CASES.values())
