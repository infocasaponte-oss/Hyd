# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Post-hoc classifier calibration, independent of decoding temperature."""
import math


def probabilities(logits, temperature):
    if temperature <= 0 or not logits or any(not math.isfinite(x) for x in logits):
        raise ValueError("finite logits and positive temperature required")
    values = [(x - max(logits)) / temperature for x in logits]
    exp = [math.exp(x) for x in values]
    return [x / sum(exp) for x in exp]


def metrics(logits, labels, temperature=1.0, bins=10):
    if not logits or len(logits) != len(labels) or bins < 1:
        raise ValueError("nonempty aligned calibration arrays required")
    width = len(logits[0])
    if width < 2 or any(len(row) != width for row in logits):
        raise ValueError("consistent multiclass logits required")
    if any(type(y) is not int or not 0 <= y < width for y in labels):
        raise ValueError("invalid labels")
    rows = [probabilities(row, temperature) for row in logits]
    nll = -sum(math.log(max(p[y], 1e-300)) for p, y in zip(rows, labels)) / len(rows)
    brier = sum(sum((v - int(i == y)) ** 2 for i, v in enumerate(p))
                for p, y in zip(rows, labels)) / len(rows)
    groups = [[] for _ in range(bins)]
    for p, y in zip(rows, labels):
        confidence = max(p)
        correct = p.index(confidence) == y
        groups[min(int(confidence * bins), bins - 1)].append((confidence, correct))
    ece = sum(abs(sum(c for c, _ in g) - sum(ok for _, ok in g))
              for g in groups if g) / len(rows)
    return {"nll": nll, "brier": brier, "ece": ece, "bins": bins, "examples": len(rows)}


def fit_temperature(logits, labels):
    candidates = [math.exp(-3 + i * 6 / 120) for i in range(121)] + [1.0]
    best = min(candidates, key=lambda t: metrics(logits, labels, t)["nll"])
    return {"temperature": best, "before": metrics(logits, labels),
            "after": metrics(logits, labels, best),
            "search_boundary": best in (min(candidates), max(candidates)),
            "scope": "Calibration fit only; independent test still required", "approved": False}


def risk_coverage(logits, labels, temperature=1.0):
    metrics(logits, labels, temperature)  # Validate before computing selective metrics.
    predictions = [probabilities(row, temperature) for row in logits]
    curve = []
    for threshold in [i / 20 for i in range(21)]:
        accepted = [(p.index(max(p)) == y) for p, y in zip(predictions, labels) if max(p) >= threshold]
        curve.append({"threshold": threshold, "coverage": len(accepted) / len(labels),
                      "selective_accuracy": sum(accepted) / len(accepted) if accepted else None})
    return curve
