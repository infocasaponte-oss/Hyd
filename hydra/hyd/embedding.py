# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hyd ranker on a frozen contextual encoder: encoder embeddings -> HYDRA-trained linear head.

The encoder is interchangeable and recorded in the model file: today the HYDRA v8 GGUF served by
llama-server with ``--embeddings`` (Qwen2.5-1.5B base, Apache-2.0), later HYDRA Base. Only the head
(standardisation, weights, bias, temperature) is trained by HYDRA. The head knows a fixed label set;
any other option set gets a uniform distribution, which the engine reports as unsupported/abstained.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from hydra.core.atomic import write_text_atomic
from hydra.hyd.model import render

FORMAT = "hyd-embedding-head/1"


class LlamaCppEncoder:
    """OpenAI-compatible ``/v1/embeddings`` of a local llama-server started with ``--embeddings``."""

    LOOPBACK = {"127.0.0.1", "localhost", "::1"}

    def __init__(self, endpoint: str, model: str, dims: int, timeout_s: float = 30):
        from urllib.parse import urlsplit

        # Parse instead of prefix-matching: deceptive host suffixes and URL userinfo
        # must never receive user requests.
        parts = urlsplit(endpoint)
        try:
            port = parts.port
        except ValueError:
            port = None
        if (parts.scheme != "http" or parts.hostname not in self.LOOPBACK or parts.username or parts.password
                or port is None or parts.query or parts.fragment or parts.path not in ("", "/")):
            raise ValueError("Hyd encoder must be a plain local endpoint such as http://127.0.0.1:18094")
        self.endpoint, self.model, self.dims, self.timeout_s = endpoint.rstrip("/"), model, dims, timeout_s

    def embed(self, texts: list[str], deadline: float | None = None) -> np.ndarray:
        import httpx

        timeout = self.timeout_s if deadline is None else max(0.05, min(self.timeout_s, deadline - time.monotonic()))
        vectors = []
        try:
            # a live local server accepts at once; Windows retries refused localhost SYNs for ~2 s
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(0.5, timeout))) as client:
                for start in range(0, len(texts), 32):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Hyd encoder deadline exceeded")
                    response = client.post(self.endpoint + "/v1/embeddings",
                                           json={"model": self.model, "input": texts[start:start + 32]})
                    if response.status_code != 200:
                        raise RuntimeError(f"Hyd encoder returned HTTP {response.status_code}")
                    data = sorted(response.json()["data"], key=lambda item: item["index"])
                    vectors += [item["embedding"] for item in data]
        except httpx.ConnectTimeout as exc:
            raise RuntimeError("Hyd encoder unavailable: not accepting connections") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError("Hyd encoder timed out") from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # encoder down or malformed reply: a backend failure, never "invalid input"
            raise RuntimeError(f"Hyd encoder unavailable: {type(exc).__name__}") from exc
        array = np.asarray(vectors, dtype=np.float64)
        if array.shape != (len(texts), self.dims) or not np.isfinite(array).all():
            raise RuntimeError("Hyd encoder returned embeddings of the wrong shape or non-finite values")
        return array


class HydraBaseEncoder:
    """HYDRA Base (own weights) as encoder: mean of the last hidden states over real tokens.

    Loaded lazily on first use and checked against the recorded weight and tokenizer hashes, so a
    swapped checkpoint can never silently feed a head trained on another one."""

    CONFIG_FILES = ("config.json",)
    TOKENIZER_CONFIG_FILES = ("tokenizer_config.json", "special_tokens_map.json")

    @classmethod
    def identity(cls, model_dir: Path, tokenizer_dir: Path) -> str:
        """Hash of every configuration file from_pretrained reads (rope, bos/eos handling, ...)."""
        digest = hashlib.sha256()
        for folder, names in ((model_dir, cls.CONFIG_FILES), (tokenizer_dir, cls.TOKENIZER_CONFIG_FILES)):
            for name in names:
                path = folder / name
                digest.update(name.encode() + b"\x00" + (path.read_bytes() if path.is_file() else b"<absent>"))
        return digest.hexdigest()

    def __init__(self, model_dir: str, tokenizer_dir: str, dims: int, weights_sha256: str, tokenizer_sha256: str,
                 device: str = "cpu", max_tokens: int = 512, batch: int = 16, config_sha256: str | None = None):
        self.model_dir, self.tokenizer_dir, self.dims = Path(model_dir), Path(tokenizer_dir), dims
        self.weights_sha256, self.tokenizer_sha256 = weights_sha256, tokenizer_sha256
        self.device, self.max_tokens, self.batch = device, max_tokens, batch
        self.config_sha256 = config_sha256
        self._model = self._tokenizer = None

    def _load(self):
        import torch
        from transformers import AutoTokenizer, LlamaModel

        from hydra.training.base_corpus import file_sha256
        if (file_sha256(self.model_dir / "model.safetensors") != self.weights_sha256
                or file_sha256(self.tokenizer_dir / "tokenizer.model") != self.tokenizer_sha256):
            raise RuntimeError("HYDRA Base encoder weights or tokenizer do not match the recorded hashes")
        if self.config_sha256 is not None and self.identity(self.model_dir, self.tokenizer_dir) != self.config_sha256:
            raise RuntimeError("HYDRA Base encoder configuration files do not match the recorded hashes")
        self._tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_dir, local_files_only=True)
        model = LlamaModel.from_pretrained(self.model_dir, local_files_only=True, use_safetensors=True)
        if model.config.hidden_size != self.dims:
            raise RuntimeError("HYDRA Base encoder width does not match the head")
        self._model = model.to(torch.device(self.device)).eval()

    def embed(self, texts: list[str], deadline: float | None = None) -> np.ndarray:
        import torch

        if self._model is None:
            self._load()
        out = []
        with torch.inference_mode():
            for start in range(0, len(texts), self.batch):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Hyd encoder deadline exceeded")
                enc = self._tokenizer(texts[start:start + self.batch], return_tensors="pt", padding=True,
                                      truncation=True, max_length=self.max_tokens).to(self._model.device)
                hidden = self._model(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"],
                                     use_cache=False).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                out.append(((hidden * mask).sum(1) / mask.sum(1).clamp(min=1)).float().cpu().numpy())
        array = np.concatenate(out).astype(np.float64)
        if array.shape != (len(texts), self.dims) or not np.isfinite(array).all():
            raise RuntimeError("HYDRA Base encoder returned embeddings of the wrong shape or non-finite values")
        return array


def encoder_from(spec: dict, base: Path | None = None):
    """``base``: directory of the model file; relative encoder paths are resolved against it, so a
    head and its encoder can move together between hosts."""
    if spec.get("kind") == "llamacpp-embeddings":
        return LlamaCppEncoder(spec["endpoint"], spec["model"], int(spec["dims"]))
    if spec.get("kind") == "hydra-base-mean":
        root = base or Path.cwd()
        return HydraBaseEncoder(str(root / spec["model_dir"]), str(root / spec["tokenizer_dir"]), int(spec["dims"]),
                                spec["weights_sha256"], spec["tokenizer_sha256"], spec.get("device", "cpu"),
                                int(spec.get("max_tokens", 512)), config_sha256=spec.get("config_sha256"))
    raise ValueError(f"unsupported Hyd encoder kind: {spec.get('kind')}")


def softmax(logits: np.ndarray, temperature: float) -> np.ndarray:
    z = logits / temperature
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def fit_head(x: np.ndarray, y: np.ndarray, classes: int, l2: float, epochs: int = 300, rate: float = 0.5):
    """Full-batch multinomial logistic regression on standardised features (deterministic)."""
    w = np.zeros((x.shape[1], classes))
    b = np.zeros(classes)
    onehot = np.eye(classes)[y]
    for _ in range(epochs):
        p = softmax(x @ w + b, 1.0)
        gradient = (p - onehot) / len(x)
        w -= rate * (x.T @ gradient + l2 * w)
        b -= rate * gradient.sum(axis=0)
    return w, b


class EmbeddingRanker:
    def __init__(self, encoder, labels: list[str], mean, scale, weights, bias, temperature: float = 1.0):
        self.encoder, self.labels = encoder, list(labels)
        self.mean, self.scale = np.asarray(mean, dtype=np.float64), np.asarray(scale, dtype=np.float64)
        self.weights, self.bias = np.asarray(weights, dtype=np.float64), np.asarray(bias, dtype=np.float64)
        self.temperature = temperature
        self.training: dict = {}
        self.revision = "untrained"
        self.exclusive = True  # one encoder call at a time: llama-server runs a single slot
        self.last_input_tokens = 0

    def text_of(self, state, instructions) -> str:
        return render(state) if instructions is None else render(state) + "\nInstructions: " + render(instructions)

    def probabilities_batch(self, texts: list[str], deadline=None) -> list[dict[str, float]]:
        return self.probabilities_from_embeddings(self.encoder.embed(texts, deadline))

    def probabilities_from_embeddings(self, embeddings: np.ndarray) -> list[dict[str, float]]:
        x = (embeddings - self.mean) / self.scale
        return [dict(zip(self.labels, map(float, row))) for row in softmax(x @ self.weights + self.bias,
                                                                          self.temperature)]

    def probabilities(self, state, instructions, options: dict, deadline=None) -> dict[str, float]:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Hyd deadline exceeded")
        if set(options) != set(self.labels):
            return {key: 1 / len(options) for key in options}  # untrained option set: no opinion
        self.last_input_tokens = 0
        probabilities = self.probabilities_batch([self.text_of(state, instructions)], deadline)[0]
        return {key: probabilities[key] for key in options}

    def save(self, path: Path, encoder_spec: dict):
        payload = {"format": FORMAT, "encoder": encoder_spec, "labels": self.labels, "temperature": self.temperature,
                   "mean": self.mean.tolist(), "scale": self.scale.tolist(), "weights": self.weights.tolist(),
                   "bias": self.bias.tolist(), "training": self.training}
        write_text_atomic(path, json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        self.revision = hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path, encoder=None):
        raw = path.read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("Hyd embedding head exceeds size limit")
        data = json.loads(raw)
        if data.get("format") != FORMAT:
            raise ValueError("unsupported Hyd embedding head format")
        labels = data["labels"]
        dims = int(data["encoder"]["dims"])
        weights, bias = np.asarray(data["weights"], dtype=np.float64), np.asarray(data["bias"], dtype=np.float64)
        mean, scale = np.asarray(data["mean"], dtype=np.float64), np.asarray(data["scale"], dtype=np.float64)
        temperature = data["temperature"]
        if (weights.shape != (dims, len(labels)) or bias.shape != (len(labels),) or mean.shape != (dims,)
                or scale.shape != (dims,) or not (scale > 0).all()
                or not all(np.isfinite(a).all() for a in (weights, bias, mean, scale))
                or type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature <= 0
                or len(set(labels)) != len(labels) or not 2 <= len(labels) <= 255):
            raise ValueError("invalid Hyd embedding head parameters")
        model = cls(encoder or encoder_from(data["encoder"], path.parent), labels, mean, scale, weights, bias, float(temperature))
        model.training = data.get("training", {})
        model.revision = hashlib.sha256(raw).hexdigest()
        return model
