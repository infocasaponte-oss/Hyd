# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train Hyd only on explicitly admitted HYDRA-owned routing examples."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.hyd.controller import implementation_digest
from hydra.hyd.model import CandidateRanker
from hydra.router.decision_contract import CRITERIA
from hydra.training.calibrator import fit_temperature
from hydra.training.decision_metrics import metrics
from hyd_calibrator.admission import CONTRIBUTED_LICENSE, require_consent_and_rights, require_contributed_consent


def rows(path: Path, *, training: bool, allow_contributed: bool = False) -> list[dict]:
    """allow_contributed=False keeps Hyd v1 behaviour (only verified HYDRA-authored rows)."""
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        declared = (row.get("rights") or {}).get("license") if isinstance(row, dict) else None
        if allow_contributed and declared == CONTRIBUTED_LICENSE:
            rights = require_contributed_consent(row)
        else:
            rights = require_consent_and_rights(row)
            if rights.get("verified") is not True or rights.get("license") != "proprietary-hydra-authored":
                raise ValueError("Hyd v1 requires verified HYDRA-authored records")
        if training and (row.get("training_allowed") is not True or row.get("split") != "train"):
            raise ValueError("training row is not admitted")
        if not training and (row.get("split") != "calibration" or row.get("training_allowed") is not False):
            raise ValueError("expected non-training calibration partition")
        text = row.get("input", {}).get("query")
        label = row.get("output", {}).get("task_type")
        if not isinstance(text, str) or not text.strip() or len(text) > 50000 or label not in CRITERIA:
            raise ValueError("invalid Hyd routing record")
        result.append({"text": text, "label": label, "license": rights["license"]})
    if not result:
        raise ValueError("empty Hyd partition")
    return result


def train(train_path: Path, calibration_path: Path, out: Path, epochs: int = 80, allow_contributed: bool = False) -> dict:
    if out.exists():
        raise ValueError("output directory already exists; choose a new training run")
    training = rows(train_path, training=True, allow_contributed=allow_contributed)
    calibration = rows(calibration_path, training=False, allow_contributed=allow_contributed)
    licenses = {}
    for row in training:
        licenses[row["license"]] = licenses.get(row["license"], 0) + 1
    def normalized(text):
        return " ".join(text.casefold().split())
    train_texts = {normalized(row["text"]) for row in training}
    if any(normalized(row["text"]) in train_texts for row in calibration):
        raise ValueError("train/calibration text overlap")
    unique = {}
    for row in training:
        key = normalized(row["text"])
        if key in unique and unique[key]["label"] != row["label"]:
            raise ValueError("conflicting training targets")
        unique[key] = row
    training = list(unique.values())
    if {row["label"] for row in training} != set(CRITERIA):
        raise ValueError("training must cover every routing label")
    model = CandidateRanker()
    model.fit([row["text"] for row in training], [row["label"] for row in training], CRITERIA, epochs)
    predictions = [{"expected": row["label"], "probabilities": model.probabilities(row["text"], None, CRITERIA)}
                   for row in calibration]
    model.temperature = fit_temperature(predictions)
    model.training = {"criteria": CRITERIA, "source_sha256": hashlib.sha256(train_path.read_bytes()).hexdigest(),
                      "examples": len(training), "epochs": epochs, "rights": licenses,
                      "domain": "routing_only", "general_decision_quality": "unvalidated"}
    out.mkdir(parents=True, exist_ok=False)
    model.save(out / "model.json")
    report = {"format": "hyd-calibration/1", "model_sha256": model.revision,
              "implementation_sha256": implementation_digest(), "temperature": model.temperature,
              "dataset_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
              "criteria": CRITERIA, "rights_by_license": licenses, "min_confidence": .95, "min_margin": .1,
              "status": "SHADOW_ONLY", "independent_test": False,
              "limitation": "Template families overlap semantically; exact text separation is insufficient for promotion."}
    measured = []
    for row in calibration:
        distribution = model.probabilities(row["text"], None, CRITERIA)
        measured.append({"expected": row["label"], "selected": max(distribution, key=distribution.get),
                         "probabilities": distribution})
    report["metrics"] = metrics(measured, .95)
    write_text_atomic(out / "calibration.json", json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, default=Path("data/decision-corpus-v3/train.jsonl"))
    parser.add_argument("--calibration", type=Path, default=Path("data/decision-corpus-v3/calibration.jsonl"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--allow-contributed", action="store_true",
                        help="also admit contributed-with-consent rows (not HYDRA-authored; counted separately)")
    args = parser.parse_args()
    if not 1 <= args.epochs <= 500:
        parser.error("epochs must be 1..500")
    print(json.dumps(train(args.train, args.calibration, args.out, args.epochs, args.allow_contributed), ensure_ascii=False, indent=2))
