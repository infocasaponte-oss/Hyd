# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Independent CPU candidate ranker. No Kev code, checkpoints or runtime dependency.

Scores each candidate against the same state/instruction representation. Candidate
order and other questions cannot change that candidate's logit. This inexpensive
model is a routing baseline, not a general-purpose language understanding claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

import numpy as np

from hydra.core.atomic import write_text_atomic

FORMAT = "hyd-candidate-ranker/1"
FEATURE_VERSION = "hyd-hash-words-characters/1"
WORDS = re.compile(r"\w+", re.UNICODE)


def render(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def features(text: str, size: int) -> np.ndarray:
    vector = np.zeros(size, dtype=np.float64)
    words = WORDS.findall(text.casefold())
    grams = ["word:" + word for word in words]
    grams += ["pair:" + a + ":" + b for a, b in zip(words, words[1:])]
    normalized = " " + " ".join(words) + " "
    for width in (3, 4):
        grams.extend("char:" + normalized[i:i + width] for i in range(len(normalized) - width + 1))
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % size] += 1 if digest[4] & 1 else -1
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


class CandidateRanker:
    def __init__(self, state_dims: int = 512, option_dims: int = 128):
        self.weights = np.zeros((state_dims, option_dims), dtype=np.float64)
        self.bias = np.zeros(option_dims, dtype=np.float64)
        self.temperature = 1.0
        self.training = {}
        self.revision = "untrained"

    def logits(self, state, instructions, options: dict[str, object]) -> dict[str, float]:
        context = features(render(state) + "\nInstructions: " + render(instructions), self.weights.shape[0])
        query = context @ self.weights + self.bias
        # Evaluate separately: BLAS reduction shape cannot depend on question batching.
        return {label: float(query @ features(label + " " + render(description), len(self.bias)))
                for label, description in options.items()}

    def probabilities(self, state, instructions, options: dict[str, object], deadline=None) -> dict[str, float]:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Hyd deadline exceeded")
        logits = self.logits(state, instructions, options)
        peak = max(logits.values())
        mass = {key: math.exp((value - peak) / self.temperature) for key, value in logits.items()}
        total = math.fsum(mass.values())
        return {key: value / total for key, value in mass.items()}

    def fit(self, texts: list[str], targets: list[str], options: dict[str, object], epochs: int = 80):
        labels = sorted(options)
        contexts = np.stack([features(text + "\nInstructions: null", self.weights.shape[0]) for text in texts])
        candidates = np.stack([features(key + " " + render(options[key]), len(self.bias)) for key in labels])
        expected = np.array([labels.index(target) for target in targets])
        rng = np.random.default_rng(42)
        for epoch in range(epochs):
            order = rng.permutation(len(texts))
            rate = 3.0 / (1 + epoch / 40)
            for start in range(0, len(texts), 64):
                ids = order[start:start + 64]
                batch = contexts[ids]
                logits = (batch @ self.weights + self.bias) @ candidates.T
                logits -= logits.max(axis=1, keepdims=True)
                gradient = np.exp(logits)
                gradient /= gradient.sum(axis=1, keepdims=True)
                gradient[np.arange(len(ids)), expected[ids]] -= 1
                projected = gradient @ candidates / len(ids)
                self.weights -= rate * (batch.T @ projected + 1e-5 * self.weights)
                self.bias -= rate * projected.sum(axis=0)

    def save(self, path: Path):
        payload = {"format": FORMAT, "features": FEATURE_VERSION, "temperature": self.temperature,
                   "weights": self.weights.tolist(), "bias": self.bias.tolist(), "training": self.training}
        write_text_atomic(path, json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        self.revision = hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path):
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("Hyd model exceeds size limit")
        data = json.loads(raw)
        if data.get("format") != FORMAT or data.get("features") != FEATURE_VERSION:
            raise ValueError("unsupported Hyd model format")
        weights = np.asarray(data["weights"], dtype=np.float64)
        bias = np.asarray(data["bias"], dtype=np.float64)
        temperature = data["temperature"]
        if (weights.ndim != 2 or bias.ndim != 1 or weights.shape[1] != len(bias)
                or not 16 <= weights.shape[0] <= 4096 or not 16 <= len(bias) <= 1024
                or not np.isfinite(weights).all() or not np.isfinite(bias).all()
                or type(temperature) not in (float, int) or not math.isfinite(temperature) or temperature <= 0):
            raise ValueError("invalid Hyd model parameters")
        model = cls(*weights.shape)
        model.weights, model.bias, model.temperature = weights, bias, float(temperature)
        model.training = data.get("training", {})
        model.revision = hashlib.sha256(raw).hexdigest()
        return model
