# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Numerical variants remain admitted while each class and family receives equal mass."""
import numpy as np

from hydra.training.decision_finetune_balanced import balanced_weights


def test_variants_do_not_multiply_family_or_class_gradient_mass():
    rows = [{'text': 'Synthetic greeting variant', 'expected': 'chat', 'group_id': 'chat-family'} for _ in range(4)]
    rows += [{'text': 'Synthetic code variant', 'expected': 'coding', 'group_id': name}
             for name in ('code-family-one', 'code-family-two')]
    weights = balanced_weights(rows)
    assert len(weights) == len(rows) and np.all(weights > 0)
    assert np.isclose(weights.sum(), len(rows))
    assert np.isclose(weights[:4].sum(), weights[4:].sum())
    assert np.isclose(weights[4], weights[5])
    assert np.isclose(weights[0], weights[1])


def test_replication_changes_no_total_family_mass_after_normalization():
    original = [{'text': 'Synthetic A', 'expected': 'chat', 'group_id': 'first'},
                {'text': 'Synthetic B', 'expected': 'chat', 'group_id': 'second'},
                {'text': 'Synthetic C', 'expected': 'coding', 'group_id': 'third'}]
    repeated = [original[0]] * 7 + original[1:]
    a, b = balanced_weights(original), balanced_weights(repeated)
    assert np.isclose(a[0] / a.sum(), b[:7].sum() / b.sum())
    assert np.isclose(a[1] / a.sum(), b[7] / b.sum())
