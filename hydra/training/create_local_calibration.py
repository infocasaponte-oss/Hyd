# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fit a model-bound shadow calibrator using the calibration partition only."""
import hashlib
import json
import math
from pathlib import Path

from hydra.training.calibrator import TemperatureCalibrator, fit_temperature
from hydra.training.specialists import TextClassifier
import hydra.training.specialists as features


def create(model: Path, dataset: Path, output: Path) -> dict:
    classifier = TextClassifier.load(model)
    rows = []
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") != "calibration" or row.get("training_allowed") is True:
            raise ValueError("only reserved calibration rows may fit temperature")
        expected = row["output"]["task_type"]
        if expected not in classifier.labels:
            raise ValueError("calibration label not supported by classifier")
        rows.append({"expected": expected,
                     "probabilities": classifier.predict_proba(row["input"]["query"])})
    temperature = fit_temperature(rows)
    def loss(calibrator):
        return -sum(math.log(max(calibrator.probabilities(r["probabilities"])[r["expected"]], 1e-12))
                    for r in rows) / len(rows)
    manifest = {"format": "hydra-local-routing-calibration/1", "labels": classifier.labels,
                "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "feature_implementation_sha256": hashlib.sha256(Path(features.__file__).read_bytes()).hexdigest(),
                "calibration_dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                "temperature": temperature, "rows": len(rows),
                "nll_before": loss(TemperatureCalibrator()),
                "nll_after": loss(TemperatureCalibrator(temperature)), "status": "SHADOW_ONLY",
                "limitation": "template calibration; no independent promotion evidence"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(create(Path("models/hydra-decision-v4/classifier.json"),
                            Path("data/decision-corpus-v3/calibration.jsonl"),
                            Path("models/hydra-decision-v4/local-calibration.json")), indent=2))
