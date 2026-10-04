# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train and evaluate the lightweight HYDRA-native decision v2 head."""
from __future__ import annotations

import json
from pathlib import Path

from hydra.training.calibrator import fit_temperature
from hydra.training.decision_metrics import metrics
from hydra.training.specialists import TextClassifier, _examples


def train(corpus: Path = Path("data/decision-corpus-v3"), output: Path = Path("models/hydra-decision-v2"),
          human_dev: Path | None = Path("data/human-dev-v1.jsonl")) -> dict:
    X, y = _examples(corpus / "train.jsonl")
    if human_dev is not None and human_dev.exists():
        human_rows = [json.loads(line) for line in human_dev.read_text(encoding="utf-8").splitlines()]
        X.extend(row["text"] for row in human_rows if row.get("training_allowed") is True)
        y.extend(row["expected"] for row in human_rows if row.get("training_allowed") is True)
    classifier = TextClassifier(sorted(set(y)), dims=4096)
    classifier.fit(X, y, epochs=16, lr=0.5, seed=42)
    output.mkdir(parents=True, exist_ok=True)
    classifier.save(output / "classifier.json")
    calibration = _rows(classifier, corpus / "calibration.jsonl")
    test = _rows(classifier, corpus / "test.jsonl")
    temperature = fit_temperature(calibration)
    manifest = {"format": "hydra-decision-v2/1", "backend": "hydra-text-classifier",
                "labels": classifier.labels, "train_examples": len(X), "seed": 42,
                "calibration_temperature": temperature,
                "training_corpus": [str(corpus / "train.jsonl"), str(human_dev) if human_dev else None],
                "test_corpus": str(corpus / "test.jsonl"),
                "limitations": "Synthetic corpus; candidate head, not Kev checkpoint."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest": manifest, "calibration": metrics(calibration), "test": metrics(test)}


def _rows(classifier: TextClassifier, path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        text = row["input"]["query"]
        probabilities = classifier.predict_proba(text)
        rows.append({"id": row["id"], "expected": row["output"]["task_type"],
                     "selected": max(probabilities, key=probabilities.get), "probabilities": probabilities})
    return rows


if __name__ == "__main__":
    print(json.dumps(train(), indent=2, ensure_ascii=False))
