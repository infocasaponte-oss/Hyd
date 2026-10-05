# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fit -> select on dev -> probability calibration -> policy calibration -> report.

No input partition is regenerated, and no candidate is automatically deployed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from hydra.hyd.continual import ContinualRanker, code_digest, fit_linear, softmax
from hydra.hyd.controller import implementation_digest
from hydra.hyd.engine import typed_confidence
from hydra.router.decision_contract import CRITERIA
from hydra.training.calibrator import TemperatureCalibrator, fit_temperature
from hydra.training.decision_active_learning import check_partitions, read_rows, text_label
from hydra.training.decision_metrics import metrics, wilson_lower
from hydra.training.evidence_io import write_json

PARTS = ("fit", "dev", "cal_prob", "cal_policy", "test")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def group(row):
    value = row.get("group_id") or row.get("scenario_id") or row.get("template_id") or row.get("family")
    if not isinstance(value, str) or not value or value == text_label(row)[1]:
        raise ValueError("scenario group required (not class name)")
    return value


def validate(parts):
    if set(parts) != set(PARTS) or any(not rows for rows in parts.values()):
        raise ValueError("five nonempty partitions required")
    check_partitions(parts)
    for name, rows in parts.items():
        seen = set()
        for row in rows:
            text, label = text_label(row)
            group(row)
            if label not in CRITERIA or not row.get("id") or row["id"] in seen:
                raise ValueError("invalid/duplicate ID or unknown routing label")
            seen.add(row["id"])
            if name == "fit" and row.get("training_allowed") is not True:
                raise ValueError("fit row not admitted")
            if name != "fit" and row.get("training_allowed") is not False:
                raise ValueError("evaluation row cannot be training-allowed")
            if hashlib.sha256(text.encode()).hexdigest() != row.get("text_sha256"):
                raise ValueError("text digest mismatch")
    if {text_label(r)[1] for r in parts["fit"]} != set(CRITERIA):
        raise ValueError("fit must cover ten routes")


def scored(rows, p, labels):
    return [{"id": r["id"], "text_sha256": r["text_sha256"], "group_id": group(r),
             "expected": text_label(r)[1], "selected": labels[int(np.argmax(probs))],
             "probabilities": dict(zip(labels, map(float, probs)))} for r, probs in zip(rows, p)]


def report_metrics(rows):
    score = metrics(rows)
    per = {}
    for label in CRITERIA:
        tp = sum(r["selected"] == label and r["expected"] == label for r in rows)
        fp = sum(r["selected"] == label and r["expected"] != label for r in rows)
        fn = sum(r["selected"] != label and r["expected"] == label for r in rows)
        per[label] = {"support": tp + fn, "recall": tp / (tp + fn) if tp + fn else None,
                      "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}
    score["per_class"] = per
    score["macro_f1_ten_routes"] = sum(p["f1"] for p in per.values()) / len(CRITERIA)
    return score


def train_candidate(paths, out, spec, *, epochs=100, seed=42, fine_tune_epochs=0):
    out = Path(out)
    if out.exists() or not 1 <= epochs <= 2000:
        raise ValueError("new candidate output and epochs 1..2000 required")
    parts = {k: read_rows(Path(v)) for k, v in paths.items()}
    validate(parts)
    labels = sorted(CRITERIA)
    if fine_tune_epochs:
        from hydra.training.decision_finetune import tune
        # Encoder is private and versioned alongside the head; it never replaces the base cache.
        spec = tune(parts, spec, out.parent / (out.name + "-encoder"), labels, epochs=fine_tune_epochs, seed=seed)
    model = ContinualRanker(spec, labels, np.zeros((spec["dims"], len(labels))), np.zeros(len(labels)))
    vectors = {name: model.vectors([text_label(r)[0] for r in rows]) for name, rows in parts.items()}
    frequencies = Counter(group(r) for r in parts["fit"])
    weights = [1 / frequencies[group(r)] for r in parts["fit"]]
    candidates = []
    for l2 in (.0001, .01, .1):
        w, b = fit_linear(vectors["fit"], [text_label(r)[1] for r in parts["fit"]], labels,
                          epochs, l2, seed, weights)
        measured = report_metrics(scored(parts["dev"], softmax(vectors["dev"] @ w + b), labels))
        candidates.append((measured["macro_f1_ten_routes"], -measured["nll"], l2, w, b, measured))
    best = max(candidates, key=lambda c: c[:2])
    model.weights, model.bias = best[3], best[4]
    memory_trials = []
    if spec.get("memory", False):
        representatives = {}
        for i, row in enumerate(parts["fit"]):
            representatives.setdefault(group(row), i)
        indices = list(representatives.values())
        model.memory_vectors = vectors["fit"][indices]
        model.memory_targets = np.array([labels.index(text_label(parts["fit"][i])[1]) for i in indices])
        for mix in (0, .15, .3):
            model.memory_mix = mix
            measured = report_metrics(scored(parts["dev"], model.distributions(vectors["dev"]), labels))
            memory_trials.append((measured["macro_f1_ten_routes"], -measured["nll"], mix))
        model.memory_mix = max(memory_trials, key=lambda trial: trial[:2])[2]
    raw_cal = scored(parts["cal_prob"], model.distributions(vectors["cal_prob"]), labels)
    temperature = fit_temperature(raw_cal)
    calibrator = TemperatureCalibrator(temperature)
    def calibrated(v):
        probabilities = model.distributions(v)
        return np.array([list(calibrator.probabilities(dict(zip(labels, p))).values()) for p in probabilities])
    policy_rows = scored(parts["cal_policy"], calibrated(vectors["cal_policy"]), labels)
    thresholds = []
    for threshold in (.5, .7, .8, .9, .95, .99):
        accepted = [r for r in policy_rows if typed_confidence("choice", r["probabilities"]) >= threshold]
        correct = sum(r["selected"] == r["expected"] for r in accepted)
        if len(accepted) >= 30 and len(accepted) / len(policy_rows) >= .5 and wilson_lower(correct, len(accepted)) >= .95:
            thresholds.append(threshold)
    threshold = min(thresholds) if thresholds else 1.0
    model.training = {"source_sha256": {k: file_sha(v) for k, v in paths.items()}, "seed": seed,
                      "epochs": epochs, "l2": best[2], "selection": "dev_only",
                      "post_temperature": temperature, "memory_mix": model.memory_mix,
                      "weighting": "equal_scenario", "policy_passed": bool(thresholds), "status": "SHADOW_ONLY"}
    out.mkdir(parents=True)
    model.save(out / "model.json")
    reloaded = ContinualRanker.load(out / "model.json")
    probe = text_label(parts["dev"][0])[0]
    if not np.allclose(list(model.predict_proba(probe).values()), list(reloaded.predict_proba(probe).values()), atol=1e-8):
        raise ValueError("full encoder/head reload parity failed")
    calibration = {"format": "hyd-calibration/1", "model_sha256": model.revision,
        "implementation_sha256": implementation_digest(), "temperature": model.temperature,
        "post_temperature": temperature,
        "portable_routing_code_sha256": code_digest(),
        "dataset_sha256": file_sha(paths["cal_prob"]), "policy_dataset_sha256": file_sha(paths["cal_policy"]),
        "criteria": CRITERIA, "min_confidence": threshold, "min_margin": 0 if thresholds else 1,
        "policy_passed": bool(thresholds), "independent_test": False, "status": "SHADOW_ONLY"}
    write_json(out / "calibration.json", calibration)
    test_predictions = scored(parts["test"], calibrated(vectors["test"]), labels)
    (out / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in test_predictions), encoding="utf-8")
    report = {"format": "hyd-candidate-evaluation/1", "authority": False, "status": "SHADOW_ONLY",
        "domain": "routing_only", "independent_test": False, "model_revision": model.revision,
        "reload_parity": True, "spec": spec, "training": model.training,
        "selection_trials": [{"l2": c[2], "dev": c[5]} for c in candidates],
        "memory_trials": [{"dev_macro_f1": t[0], "dev_nll": -t[1], "mix": t[2]} for t in memory_trials],
        "probability_calibration": report_metrics(scored(parts["cal_prob"],
             calibrated(vectors["cal_prob"]), labels)),
        "policy_calibration": report_metrics(policy_rows), "policy_passed": bool(thresholds),
        "test": report_metrics(test_predictions)}
    report["artifact_sha256"] = {p.name: file_sha(p) for p in (out / "model.json", out / "calibration.json", out / "predictions.jsonl")}
    write_json(out / "report.json", report)
    return report


def prepare(corpus, out, held_person):
    """Development-only import of already labelled consenting people, never a new blind test."""
    if out.exists():
        raise FileExistsError("new snapshot required")
    parts = {k: [] for k in PARTS}
    for original in read_rows(corpus):
        text, label = text_label(original)
        if original.get("consent") is not True or not original.get("rights") or not original.get("person"):
            raise ValueError("consenting declared source/person required")
        family = group(original)
        bucket = int(hashlib.sha256(family.encode()).hexdigest()[:8], 16) % 10
        split = "test" if original["person"] == held_person else ("dev" if bucket == 0 else
            "cal_prob" if bucket == 1 else "cal_policy" if bucket == 2 else "fit")
        parts[split].append({**original, "text": text, "expected": label, "group_id": family,
                            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "training_allowed": split == "fit", "split": split})
    validate(parts)
    out.mkdir(parents=True)
    paths = {}
    for name, rows in parts.items():
        path = out / (name + ".jsonl")
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        paths[name] = str(path.resolve())
    write_json(out / "manifest.json", {"source_sha256": file_sha(corpus), "paths": paths,
        "counts": {k: len(v) for k, v in parts.items()}, "independent_test": False,
        "reason": "previously inspected human corpus; development LOPO only"})
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--held-person", required=True)
    t = sub.add_parser("train")
    t.add_argument("--snapshot", type=Path, required=True)
    t.add_argument("--encoder-spec", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--epochs", type=int, default=100)
    t.add_argument("--seed", type=int, default=42)
    t.add_argument("--fine-tune-epochs", type=int, default=0)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.corpus, args.out, args.held_person)
    else:
        result = train_candidate(json.loads((args.snapshot / "manifest.json").read_text())["paths"], args.out,
            json.loads(args.encoder_spec.read_text()), epochs=args.epochs, seed=args.seed, fine_tune_epochs=args.fine_tune_epochs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
