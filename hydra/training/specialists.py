# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Non-LLM specialists: the Model Factory does not always fabricate LLMs.

For narrow, structured decisions (routing, tool selection, critic verdicts) an
``encoder + classifier`` is often better, cheaper and faster than a generative model. This
module trains a real hashed-n-gram multinomial logistic-regression classifier (numpy, CPU,
seconds) from HYDRA datasets and serves it; it is the first HYDRA-native model (e.g.
HYDRA-Router) produced entirely from HYDRA's own verified traces."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

TOKEN = re.compile(r"\w+|[^\w\s]", re.U)


def _features(text: str, dims: int) -> dict[int, float]:
    toks = [t.lower() for t in TOKEN.findall(text)]
    grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    # Character n-grams make the specialist robust to human paraphrases,
    # inflections and spelling variants that do not share exact word tokens.
    normalized = "  " + " ".join(toks) + "  "
    grams.extend(normalized[i:i+n] for n in (3, 4, 5) for i in range(len(normalized) - n + 1))
    f: dict[int, float] = {}
    for g in grams:
        idx = _stable(g) % dims
        f[idx] = f.get(idx, 0.0) + 1.0
    n = math.sqrt(sum(v * v for v in f.values())) or 1.0
    return {k: v / n for k, v in f.items()}


def _stable(s: str) -> int:
    import hashlib

    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


class TextClassifier:
    def __init__(self, labels: list[str], dims: int = 16384) -> None:
        self.labels = labels
        self.dims = dims
        self.W = [[0.0] * dims for _ in labels]
        self.b = [0.0] * len(labels)

    def _logits(self, f: dict[int, float]) -> list[float]:
        return [self.b[k] + sum(self.W[k][i] * v for i, v in f.items()) for k in range(len(self.labels))]

    def predict_proba(self, text: str) -> dict[str, float]:
        z = self._logits(_features(text, self.dims))
        m = max(z)
        e = [math.exp(x - m) for x in z]
        s = sum(e)
        return {lab: round(v / s, 4) for lab, v in zip(self.labels, e)}

    def predict(self, text: str) -> tuple[str, float]:
        p = self.predict_proba(text)
        best = max(p, key=p.get)
        return best, p[best]

    def fit(self, X: list[str], y: list[str], epochs: int = 12, lr: float = 0.5, l2: float = 1e-4, seed: int = 0) -> None:
        import random

        rng = random.Random(seed)
        data = [(_features(x, self.dims), self.labels.index(t)) for x, t in zip(X, y)]
        for ep in range(epochs):
            rng.shuffle(data)
            for f, t in data:
                z = self._logits(f)
                m = max(z)
                e = [math.exp(v - m) for v in z]
                s = sum(e)
                for k in range(len(self.labels)):
                    g = e[k] / s - (1.0 if k == t else 0.0)
                    if abs(g) < 1e-6:
                        continue
                    row = self.W[k]
                    for i, v in f.items():
                        row[i] -= lr * (g * v + l2 * row[i])
                    self.b[k] -= lr * g
            lr *= 0.85

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sparse = [{str(i): round(w, 6) for i, w in enumerate(row) if abs(w) > 1e-7} for row in self.W]
        path.write_text(json.dumps({"format": "hydra-text-classifier/1", "labels": self.labels, "dims": self.dims,
                                    "W": sparse, "b": self.b}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> TextClassifier:
        d = json.loads(path.read_text(encoding="utf-8"))
        c = cls(d["labels"], d["dims"])
        c.W = [[0.0] * c.dims for _ in c.labels]
        for k, row in enumerate(d["W"]):
            for i, w in row.items():
                c.W[k][int(i)] = w
        c.b = d["b"]
        return c


def _examples(path: Path) -> tuple[list[str], list[str]]:
    X, y = [], []
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        rows = pq.read_table(path).to_pylist()
        # CorpusStore.write_table encodes nested structures as JSON columns.
        for row in rows:
            for key in ("messages", "input", "output"):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
    else:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        if "messages" in r:  # sft rows: user -> assistant JSON label
            user = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
            ans = next((m["content"] for m in r["messages"] if m["role"] == "assistant"), "")
            try:
                label = json.loads(ans).get("task_type")
            except (json.JSONDecodeError, AttributeError):
                label = None
        else:  # raw corpus records
            user = (r.get("input") or {}).get("query") or (r.get("input") or {}).get("prompt", "")
            label = (r.get("output") or {}).get("task_type") or (r.get("output") or {}).get("label")
        if user and label:
            X.append(user)
            y.append(str(label))
    return X, y


def train_text_classifier(train_file: Path, valid_file: Path | None, out_dir: Path, seed: int = 0) -> dict[str, Any]:
    X, y = _examples(train_file)
    if not X:
        raise RuntimeError("no labelled examples (need routing_decision records or {'task_type':..} targets)")
    labels = sorted(set(y))
    clf = TextClassifier(labels)
    clf.fit(X, y, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    clf.save(out_dir / "classifier.json")
    train_acc = sum(clf.predict(x)[0] == t for x, t in zip(X, y)) / len(X)
    out: dict[str, Any] = {"backend": "builtin", "labels": labels, "train_examples": len(X),
                           "train_accuracy": round(train_acc, 4)}
    if valid_file is not None:
        Xv, yv = _examples(valid_file)
        if Xv:
            out["valid_accuracy"] = round(sum(clf.predict(x)[0] == t for x, t in zip(Xv, yv)) / len(Xv), 4)
            out["valid_examples"] = len(Xv)
    out["validation_status"] = "measured" if "valid_accuracy" in out else "not_evaluated"
    return out
