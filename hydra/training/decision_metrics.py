# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Calibration diagnostics over labelled data; threshold selection uses calibration only."""
import math


def wilson_lower(correct: int, total: int) -> float:
    if not total:
        return 0.0
    z = 1.96
    p = correct / total
    return (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) / (1+z*z/total)


def metrics(rows: list[dict], threshold: float = 0) -> dict:
    usable = [r for r in rows if r.get("probabilities") and r.get("expected") in r["probabilities"]]
    accepted = [r for r in usable if max(r["probabilities"].values()) >= threshold]
    correct = sum(r["selected"] == r["expected"] for r in accepted)
    bins = []
    for i in range(10):
        group = [r for r in usable if min(int(max(r["probabilities"].values())*10), 9) == i]
        if group:
            bins.append({"bin": i, "n": len(group),
                         "confidence": sum(max(r["probabilities"].values()) for r in group)/len(group),
                         "accuracy": sum(r["selected"] == r["expected"] for r in group)/len(group)})
    return {"requested": len(rows), "valid": len(usable), "accepted": len(accepted),
            "coverage": len(accepted)/len(rows) if rows else 0,
            "accuracy": correct/len(accepted) if accepted else None,
            "accuracy_wilson_lower_95": wilson_lower(correct, len(accepted)),
            "ece_10_bins": sum(b["n"]*abs(b["accuracy"]-b["confidence"]) for b in bins)/len(usable) if usable else None,
            "brier_multiclass_sum": sum(sum((p-float(k == r["expected"]))**2
                                           for k, p in r["probabilities"].items()) for r in usable)/len(usable) if usable else None,
            "nll": -sum(math.log(max(r["probabilities"][r["expected"]], 1e-12)) for r in usable)/len(usable) if usable else None,
            "bins": bins}


def select_threshold(calibration: list[dict]) -> float:
    # Predeclared selective accuracy target; abstain on all if none qualifies.
    for threshold in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        score = metrics(calibration, threshold)
        if score["coverage"] >= 0.5 and (score["accuracy"] or 0) >= 0.95:
            return threshold
    return 1.01
