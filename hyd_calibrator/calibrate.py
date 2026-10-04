# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fit temperature and thresholds on calibration only; never edit source weights."""

import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .atomic import write_text_atomic
from .contract import CRITERIA
from .evaluation import implementation_sha256, load_rows, selective
from .model import CandidateRanker


def probabilities(logits, temperature):
    scores = logits / temperature
    scores -= scores.max(axis=1, keepdims=True)
    mass = np.exp(scores)
    return mass / mass.sum(axis=1, keepdims=True)


def nll(logits, targets, temperature):
    scores = logits / temperature
    peak = scores.max(axis=1)
    return float(
        np.mean(peak + np.log(np.exp(scores - peak[:, None]).sum(axis=1)) - scores[np.arange(len(targets)), targets])
    )


def fit_temperature(logits, targets):
    # NLL is convex in inverse temperature; bounded golden-section search.
    left, right = 0.01, 100.0
    ratio = (math.sqrt(5) - 1) / 2
    a, b = right - ratio * (right - left), left + ratio * (right - left)
    fa, fb = nll(logits, targets, 1 / a), nll(logits, targets, 1 / b)
    for _ in range(100):
        if fa < fb:
            right, b, fb = b, a, fa
            a = right - ratio * (right - left)
            fa = nll(logits, targets, 1 / a)
        else:
            left, a, fa = a, b, fb
            b = left + ratio * (right - left)
            fb = nll(logits, targets, 1 / b)
    candidates = [0.01, 100.0, 1.0, 1 / ((left + right) / 2)]
    return min(candidates, key=lambda temperature: nll(logits, targets, temperature))


def calibrate(model_path, dataset, out, target=0.95, min_coverage=0.1, train_dataset=None):
    if not 0 < target < 1 or not 0 <= min_coverage <= 1:
        raise ValueError("invalid accuracy target or coverage")
    model_path, dataset, out = Path(model_path), Path(dataset), Path(out)
    if out.resolve() == model_path.parent.resolve():
        raise ValueError("choose a separate output directory")
    rows = load_rows(dataset, split="calibration")
    model = CandidateRanker.load(model_path)
    if model.training.get("criteria") != CRITERIA:
        raise ValueError("routing criteria mismatch")
    if hashlib.sha256(dataset.read_bytes()).hexdigest() == model.training.get("source_sha256"):
        raise ValueError("calibration dataset is the training source")
    if train_dataset:
        train_dataset = Path(train_dataset)
        if hashlib.sha256(train_dataset.read_bytes()).hexdigest() != model.training.get("source_sha256"):
            raise ValueError("training source hash mismatch")
        train_rows = load_rows(train_dataset)
        if any(r.get("split") != "train" or r.get("training_allowed") is not True for r in train_rows):
            raise ValueError("training source requires admitted train rows")
        train_texts = {" ".join(r["input"]["query"].casefold().split()) for r in train_rows}
        if any(" ".join(r["input"]["query"].casefold().split()) in train_texts for r in rows):
            raise ValueError("train/calibration text overlap")
    labels = list(CRITERIA)
    logits = np.array([list(model.logits(r["input"]["query"], None, CRITERIA).values()) for r in rows])
    targets = np.array([labels.index(r["output"]["task_type"]) for r in rows])
    original_temperature = model.temperature
    temperature = fit_temperature(logits, targets)
    before, after = nll(logits, targets, original_temperature), nll(logits, targets, temperature)
    if before < after:
        temperature, after = original_temperature, before
    model.temperature = temperature
    p = probabilities(logits, temperature)
    ordered = np.sort(p, axis=1)
    confidence, margins = ordered[:, -1].tolist(), (ordered[:, -1] - ordered[:, -2]).tolist()
    hits = (p.argmax(axis=1) == targets).tolist()
    curve = []
    for threshold in (0.0, 0.4, 0.55, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99, 1.0):
        for margin in (0.0, 0.1, 0.2):
            curve.append(
                {
                    "min_confidence": threshold,
                    "min_margin": margin,
                    **selective(confidence, margins, hits, threshold, margin),
                }
            )
    eligible = [r for r in curve if r["coverage"] >= min_coverage and r["accuracy_wilson_lower_95"] >= target]
    chosen = max(eligible, key=lambda r: (r["coverage"], r["accuracy_wilson_lower_95"])) if eligible else None
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "model.json")
    result = {
        "format": "hyd-standalone-calibration/1",
        "model_sha256": model.revision,
        "source_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "calibrator_implementation_sha256": implementation_sha256(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "train_overlap_checked": train_dataset is not None,
        "criteria": CRITERIA,
        "temperature": temperature,
        "min_confidence": chosen["min_confidence"] if chosen else 1.0,
        "min_margin": chosen["min_margin"] if chosen else 1.0,
        "target_wilson_lower_95": target,
        "minimum_coverage": min_coverage,
        "target_met": chosen is not None,
        "abstain_all": chosen is None,
        "selected": chosen,
        "nll_before": before,
        "nll_after": after,
        "curve": curve,
        "status": "SHADOW_ONLY",
        "independent_test": False,
        "runtime_compatible": False,
        "limitation": "Calibration-selected intervals are diagnostic, not independent evidence. Standalone format requires explicit Hyd integration.",
    }
    write_text_atomic(out / "calibration.json", json.dumps(result, indent=2, allow_nan=False))
    return result
