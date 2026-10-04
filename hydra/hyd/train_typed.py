# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Native training for dynamic Choice, Noul and Score questions.

Records use HYDRA's own schema: state, question, target (probability mapping),
split, family, training_allowed and verified rights. No external datasets loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from hydra.core.atomic import write_text_atomic
from hydra.hyd.engine import HydEngine
from hydra.hyd.controller import implementation_digest
from hydra.hyd.model import CandidateRanker, features, render
from hydra.router.decision_contract import CRITERIA
from hydra.training.calibrator import fit_temperature
from hydra.training.decision_metrics import metrics


def options(question):
    kind, criteria = question["type"], question.get("criteria")
    if kind == "choice":
        return criteria
    if kind == "noul":
        return {"false": (criteria or {}).get("false", "false"), "true": (criteria or {}).get("true", "true")}
    return {str(i): value for i, value in enumerate(criteria)}


def read_partition(path: Path, split: str, *, allow_licensed: bool = False):
    records = []
    validator = HydEngine(CandidateRanker())
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rights = row.get("rights", {})
        owned = rights.get("license") == "proprietary-hydra-authored"
        licensed = False
        if allow_licensed and rights.get("source_manifest_sha256"):
            from hydra.training.base_data_policy import admit_record
            licensed = admit_record(str(rights.get("license") or "").split(", ")).allowed
        if (rights.get("verified") is not True or not (owned or licensed)
                or row.get("split") != split or row.get("training_allowed") is not (split == "train")
                or not isinstance(row.get("family"), str) or not row["family"]):
            raise ValueError("typed partition requires admitted owned records with explicit family and split")
        validator.admit(row["state"], {"q": row["question"]})
        candidates, target = options(row["question"]), row["target"]
        if (set(target) != set(candidates) or any(type(p) not in (float, int) or not math.isfinite(p)
                or not 0 <= p <= 1 for p in target.values()) or abs(math.fsum(target.values()) - 1) > 1e-8):
            raise ValueError("target must be a full normalized probability distribution")
        records.append(row)
    if not records:
        raise ValueError("empty typed partition")
    return records


def train(train_path: Path, calibration_path: Path, out: Path, epochs: int = 50):
    training = read_partition(train_path, "train")
    calibration = read_partition(calibration_path, "calibration")
    # Family separation is stricter than string separation: prevent template leakage.
    if {r["family"] for r in training} & {r["family"] for r in calibration}:
        raise ValueError("typed train/calibration families overlap")
    if {render(r["state"]) for r in training} & {render(r["state"]) for r in calibration}:
        raise ValueError("typed train/calibration states overlap")
    model = CandidateRanker()
    examples = []
    domains = {}
    for row in training:
        question = row["question"]
        candidates = options(question)
        keys = sorted(candidates)
        x = features(render(row["state"]) + "\nInstructions: " + render(question.get("instructions")), 512)
        matrix = np.stack([features(key + " " + render(candidates[key]), 128) for key in keys])
        target = np.array([row["target"][key] for key in keys])
        examples.append((x, matrix, target))
        canonical = {"type": question["type"], "criteria": question.get("criteria"),
                     "instructions": question.get("instructions")}
        domains[render(canonical)] = canonical
    rng = np.random.default_rng(42)
    for epoch in range(epochs):
        for index in rng.permutation(len(examples)):
            x, matrix, target = examples[index]
            logits = matrix @ (x @ model.weights + model.bias)
            logits -= logits.max()
            p = np.exp(logits)
            p /= p.sum()
            gradient = (p - target) @ matrix
            rate = .5 / (1 + epoch / 25)
            model.weights -= rate * (np.outer(x, gradient) + 1e-5 * model.weights)
            model.bias -= rate * gradient
    scored = []
    for row in calibration:
        distribution = model.probabilities(row["state"], row["question"].get("instructions"), options(row["question"]))
        scored.append({"expected": max(row["target"], key=row["target"].get), "probabilities": distribution,
                       "selected": max(distribution, key=distribution.get)})
    # Soft-target Score/Noul loss needs soft labels. Avoid miscalibrating them
    # with an argmax target: fit T on hard targets only, leave T=1 otherwise.
    hard_rows = [r for r, source in zip(scored, calibration) if max(source["target"].values()) == 1]
    model.temperature = fit_temperature(hard_rows) if hard_rows else 1.0
    model.training = {"question_domains": list(domains.values()), "examples": len(training), "epochs": epochs,
                      "source_sha256": hashlib.sha256(train_path.read_bytes()).hexdigest(),
                      "rights": "proprietary-hydra-authored", "domain": "typed_registered_questions",
                      "general_decision_quality": "unvalidated"}
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "model.json")
    report = {"format": "hyd-typed-training/1", "model_revision": model.revision,
              "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
              "temperature": model.temperature, "status": "REQUIRES_INDEPENDENT_EVALUATION",
              "uncalibrated_argmax_diagnostics": metrics(scored), "training": model.training}
    write_text_atomic(out / "training.json", json.dumps(report, ensure_ascii=False, indent=2))
    manifest = {"format": "hyd-calibration/1", "model_sha256": model.revision,
                "implementation_sha256": implementation_digest(), "temperature": model.temperature,
                "dataset_sha256": report["calibration_sha256"], "criteria": CRITERIA,
                "min_confidence": .95, "min_margin": .1, "status": "SHADOW_ONLY",
                "independent_test": False, "limitation": "Registered questions only; no independent promotion evidence."}
    write_text_atomic(out / "calibration.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.epochs <= 500:
        parser.error("epochs must be 1..500")
    print(json.dumps(train(args.train, args.calibration, args.out, args.epochs), ensure_ascii=False, indent=2))
