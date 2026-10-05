# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Versioned routing-only linear heads for the continuous-learning factory."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from hydra.core.atomic import write_text_atomic
from hydra.hyd.model import features, render

FORMAT = "hyd-continual-routing/1"


def code_digest():
    paths = [Path(__file__), Path(__file__).with_name("model.py"), Path(__file__).with_name("continual_controller.py"),
             Path(__file__).parents[1] / "training/calibrator.py", Path(__file__).parents[1] / "training/decision_finetune.py"]
    return hashlib.sha256(b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in paths)).hexdigest()


def softmax(z, temperature=1):
    z = z / temperature
    e = np.exp(z - z.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class ContinualRanker:
    def __init__(self, spec, labels, weights, bias, temperature=1):
        self.spec, self.labels = dict(spec), list(labels)
        self.weights, self.bias = np.asarray(weights, float), np.asarray(bias, float)
        self.temperature, self.training = float(temperature), {}
        self.revision, self._encoder = "unsaved", None
        self.exclusive = spec["kind"] != "hash"
        self.last_input_tokens = 0
        self.memory_vectors, self.memory_targets, self.memory_mix = None, None, 0.0

    def distributions(self, vectors):
        p = softmax(vectors @ self.weights + self.bias, self.temperature)
        if self.memory_mix:
            similarity = vectors @ self.memory_vectors.T
            neighbors = np.argsort(-similarity, axis=1)[:, :min(5, len(self.memory_vectors))]
            memory = np.zeros_like(p)
            for i, chosen in enumerate(neighbors):
                weights = np.exp(5 * (similarity[i, chosen] - similarity[i, chosen].max()))
                for index, weight in zip(chosen, weights):
                    memory[i, int(self.memory_targets[index])] += weight
                memory[i] /= memory[i].sum()
            p = (1 - self.memory_mix) * p + self.memory_mix * memory
        return p

    def vectors(self, texts):
        kind = self.spec["kind"]
        if kind == "hash":
            return np.stack([features(t, self.weights.shape[0]) for t in texts])
        if kind in ("minilm", "minilm-finetuned"):
            revision = self.spec.get("revision", "")
            if kind == "minilm" and not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ValueError("exact encoder revision required")
            if self._encoder is None:
                from sentence_transformers import SentenceTransformer
                if kind == "minilm-finetuned":
                    from hydra.training.decision_finetune import encoder_identity
                    if encoder_identity(self.spec["model"]) != self.spec["weights_sha256"]:
                        raise ValueError("tuned encoder changed")
                self._encoder = SentenceTransformer(self.spec["model"], revision=revision or None,
                    device=self.spec.get("device", "cpu"), local_files_only=True)
            vectors = self._encoder.encode(texts, normalize_embeddings=True, batch_size=64, convert_to_numpy=True)
        elif kind == "llamacpp":
            from hydra.hyd.embedding import LlamaCppEncoder
            model_file = Path(self.spec["model_file"])
            if hashlib.sha256(model_file.read_bytes()).hexdigest() != self.spec["weights_sha256"]:
                raise ValueError("local encoder weights changed")
            if self._encoder is None:
                self._encoder = LlamaCppEncoder(self.spec["endpoint"], self.spec["model"], self.weights.shape[0])
            vectors = self._encoder.embed(texts)
        else:
            raise ValueError("unsupported continuous encoder")
        vectors = np.asarray(vectors, float)
        if vectors.shape != (len(texts), self.weights.shape[0]) or not np.isfinite(vectors).all():
            raise ValueError("invalid encoder output")
        return vectors

    def predict_proba(self, text):
        p = self.distributions(self.vectors([text]))[0]
        if "post_temperature" in self.training:
            from hydra.training.calibrator import TemperatureCalibrator
            return TemperatureCalibrator(self.training["post_temperature"]).probabilities(dict(zip(self.labels, map(float, p))))
        return dict(zip(self.labels, map(float, p)))

    def probabilities(self, state, instructions, options, deadline=None):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("routing deadline exceeded")
        if set(options) != set(self.labels):
            return {k: 1 / len(options) for k in options}
        result = self.predict_proba(state if isinstance(state, str) else render(state))
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("routing deadline exceeded")
        return result

    def save(self, path):
        data = {"format": FORMAT, "spec": self.spec, "labels": self.labels,
                "weights": self.weights.tolist(), "bias": self.bias.tolist(),
                "temperature": self.temperature, "training": self.training,
                "implementation_sha256": code_digest(), "domain": "routing_only"}
        if self.memory_vectors is not None:
            data["memory"] = {"mix": self.memory_mix, "vectors": self.memory_vectors.tolist(),
                              "targets": self.memory_targets.tolist(), "source": "fit_only_frozen_snapshot"}
        write_text_atomic(path, json.dumps(data, allow_nan=False, ensure_ascii=False))
        self.revision = hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        raw = path.read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("routing head size limit")
        data = json.loads(raw)
        if data.get("format") != FORMAT or data.get("implementation_sha256") != code_digest():
            raise ValueError("routing implementation mismatch")
        model = cls(data["spec"], data["labels"], data["weights"], data["bias"], data["temperature"])
        dims = int(data["spec"]["dims"])
        if (not 2 <= len(model.labels) <= 255 or len(set(model.labels)) != len(model.labels)
                or not 1 <= dims <= 65536 or model.weights.shape != (dims, len(model.labels))
                or model.bias.shape != (len(model.labels),) or not np.isfinite(model.weights).all()
                or not np.isfinite(model.bias).all() or not np.isfinite(model.temperature) or model.temperature <= 0):
            raise ValueError("invalid routing parameters")
        model.training, model.revision = data["training"], hashlib.sha256(raw).hexdigest()
        if "memory" in data:
            memory = data["memory"]
            model.memory_vectors = np.asarray(memory["vectors"], float)
            model.memory_targets = np.asarray(memory["targets"], int)
            model.memory_mix = float(memory["mix"])
            if (not 0 <= model.memory_mix <= .5 or model.memory_vectors.ndim != 2
                    or model.memory_vectors.shape[1] != dims or model.memory_targets.shape != (len(model.memory_vectors),)
                    or not len(model.memory_vectors) or not np.isfinite(model.memory_vectors).all()
                    or (model.memory_targets < 0).any() or (model.memory_targets >= len(model.labels)).any()):
                raise ValueError("invalid frozen routing memory")
        return model


def fit_linear(x, targets, labels, epochs=100, l2=.01, seed=42, sample_weights=None):
    weights, bias = np.zeros((x.shape[1], len(labels))), np.zeros(len(labels))
    target = np.eye(len(labels))[[labels.index(y) for y in targets]]
    factors = np.asarray(sample_weights if sample_weights is not None else np.ones(len(x)), float)
    factors /= factors.sum()
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        order = rng.permutation(len(x))
        gradient = (softmax(x[order] @ weights + bias) - target[order]) * factors[order, None]
        weights -= 2 * (x[order].T @ gradient + l2 * weights)
        bias -= 2 * gradient.sum(axis=0)
    return weights, bias
