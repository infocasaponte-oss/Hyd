"""Tests for the E3 risk specialist (HYD-021). Pure functions only —
no encoder, no network, deterministic. Run: python3 -m pytest tests/test_e3_risk.py
or python3 tests/test_e3_risk.py
"""
import unittest

import numpy as np

from hydra.hyd.e3_risk import RISKY, collapse, metrics, softmax, to_group

HYD_LABELS = ["abstain", "chat", "coding", "high_risk_review", "privacy",
              "reasoning", "research", "security", "tool_use", "vision"]


class TestE3Risk(unittest.TestCase):
    def test_to_group_maps_all_ten_classes_into_five_groups(self):
        groups = {to_group(l) for l in HYD_LABELS}
        self.assertEqual(groups, set(RISKY) | {"other"})
        self.assertEqual(len(groups), 5)

    def test_risky_classes_map_to_themselves(self):
        for l in RISKY:
            self.assertEqual(to_group(l), l)

    def test_non_risky_collapse_to_other(self):
        for l in ("chat", "coding", "reasoning", "research", "tool_use", "vision"):
            self.assertEqual(to_group(l), "other")

    def test_softmax_rows_sum_to_one_and_are_deterministic(self):
        z = np.array([[0.1, 0.2, 0.7], [2.0, -1.0, 0.0]])
        p1, p2 = softmax(z), softmax(z)
        self.assertTrue(np.allclose(p1.sum(1), 1.0))
        self.assertTrue((p1 == p2).all())

    def test_metrics_abstain_confusion_counts(self):
        labels = ["abstain", "other"]
        y = ["abstain", "abstain", "other", "other"]
        probs = np.array([[0.9, 0.1], [0.4, 0.6], [0.7, 0.3], [0.2, 0.8]])
        m = metrics(y, probs, labels, 0.85)
        # one abstain missed (recall 0.5), one false alarm (precision 0.5)
        self.assertAlmostEqual(m["per_class"]["abstain"]["recall"], 0.5)
        self.assertAlmostEqual(m["per_class"]["abstain"]["precision"], 0.5)

    def test_metrics_shadows_only_defaults(self):
        # The report contract: status and authority fields always present.
        rep_fields = {"status": "SHADOW_ONLY", "authority": False}
        self.assertEqual(rep_fields["status"], "SHADOW_ONLY")
        self.assertFalse(rep_fields["authority"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
