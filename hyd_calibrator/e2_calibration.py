# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Separate temperature fitting and diagnostic threshold selection by group."""
import hashlib

import numpy as np

from .calibrate import fit_temperature, probabilities
from .evaluation import selective


def calibration_groups(rows):
    fit, threshold = [], []
    declared = {}
    for index, row in enumerate(rows):
        group = row.get("group_id")
        if not isinstance(group, str) or not group:
            raise ValueError("calibration requires group_id")
        for field in ("person_id", "family_id"):
            value = row.get("meta", {}).get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"calibration requires {field}")
            key = (field, value)
            if key in declared and declared[key] != group:
                raise ValueError("related calibration records have inconsistent group_id")
            declared[key] = group
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 2
        (fit if bucket == 0 else threshold).append(index)
    if not fit or not threshold:
        raise ValueError("calibration needs independent temperature and threshold groups")
    return fit, threshold


def calibrate_logits(logits, targets, rows, target=0.95, min_coverage=0.1):
    if not 0 < target < 1 or not 0 < min_coverage <= 1:
        raise ValueError("invalid target or minimum coverage")
    logits, targets = np.asarray(logits), np.asarray(targets)
    if logits.ndim != 2 or logits.shape[1] < 2 or len(logits) != len(rows) or len(targets) != len(rows):
        raise ValueError("inconsistent calibration dimensions")
    if not np.isfinite(logits).all() or not np.issubdtype(targets.dtype, np.integer) or (targets < 0).any() or (targets >= logits.shape[1]).any():
        raise ValueError("invalid logits or targets")
    fit, threshold = calibration_groups(rows)
    temperature = fit_temperature(logits[fit], targets[fit])
    p = probabilities(logits[threshold], temperature)
    ordered = np.sort(p, axis=1)
    confidence = ordered[:, -1].tolist()
    margins = (ordered[:, -1] - ordered[:, -2]).tolist()
    hits = (p.argmax(axis=1) == targets[threshold]).tolist()
    curve = []
    for confidence_limit in (0.0, 0.4, 0.55, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99, 1.0):
        for margin_limit in (0.0, 0.1, 0.2):
            curve.append({"min_confidence": confidence_limit, "min_margin": margin_limit,
                          **selective(confidence, margins, hits, confidence_limit, margin_limit)})
    eligible = [point for point in curve if point["coverage"] >= min_coverage
                and point["accuracy_wilson_lower_95"] >= target]
    chosen = max(eligible, key=lambda point: (point["coverage"], point["accuracy_wilson_lower_95"])) if eligible else None
    return {"temperature": temperature, "min_confidence": chosen["min_confidence"] if chosen else 1.0,
            "min_margin": chosen["min_margin"] if chosen else 1.0, "abstain_all": chosen is None,
            "target_met": chosen is not None, "selected": chosen, "curve": curve,
            "n_temperature": len(fit), "n_threshold": len(threshold), "target": target,
            "minimum_coverage": min_coverage, "independent_test": False,
            "limitation": "Threshold-selected Wilson intervals are diagnostic, not an independent precision guarantee."}
