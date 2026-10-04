# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train the HYDRA v4 routing specialist from admitted training data only."""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

from hydra.training.specialists import TextClassifier


def load(path: Path) -> tuple[list[str], list[str]]:
    X: list[str] = []
    y: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("training_allowed") is not True:
            continue
        if "text" in row and "expected" in row:
            text, label = row["text"], row["expected"]
        else:
            text = (row.get("input") or {}).get("query") or (row.get("input") or {}).get("prompt", "")
            label = (row.get("output") or {}).get("task_type") or (row.get("output") or {}).get("label")
        if text and label:
            X.append(str(text))
            y.append(str(label))
    return X, y


def train(train_files: list[Path], out: Path, epochs: int = 18) -> dict:
    X: list[str] = []
    y: list[str] = []
    for path in train_files:
        a, b = load(path)
        X.extend(a)
        y.extend(b)
    unique: dict[str, tuple[str, str]] = {}
    for text, label in zip(X, y):
        key = " ".join(text.casefold().split())
        if key in unique and unique[key][1] != label:
            raise ValueError("conflicting labels for the same training text")
        unique.setdefault(key, (text, label))
    raw_count = len(X)
    X = [row[0] for row in unique.values()]
    y = [row[1] for row in unique.values()]
    if not X:
        raise ValueError("no admitted training examples")
    labels = sorted(set(y))
    clf = TextClassifier(labels)
    clf.fit(X, y, epochs=epochs, seed=42)
    out.parent.mkdir(parents=True, exist_ok=True)
    clf.save(out)
    return {"format": "hydra-decision-v4-training", "examples": len(X),
            "labels": labels, "train_accuracy": round(sum(clf.predict(x)[0] == t for x, t in zip(X, y)) / len(X), 4),
            "sources": [str(p) for p in train_files], "epochs": epochs,
            "raw_examples": raw_count, "duplicates_removed": raw_count - len(X),
            "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in train_files}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("models/hydra-decision-v4/classifier.json"))
    args = parser.parse_args()
    report = train([Path("data/decision-corpus-v3/train.jsonl"), Path("data/human-dev-v1.jsonl"), Path("data/human-dev-v2.jsonl")], args.out)
    args.out.with_suffix(".report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
