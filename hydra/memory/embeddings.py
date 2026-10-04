# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Embeddings. Default: deterministic feature hashing (no model required).
Production: any OpenAI-compatible /embeddings endpoint (vLLM, llama.cpp, cloud)."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from abc import ABC, abstractmethod

import httpx

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _TOKEN.findall(text)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder(Embedder):
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm else v

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OllamaEmbedder(Embedder):
    def __init__(self, base_url: str, model: str = "nomic-embed-text") -> None:
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        r = await self.client.post("/api/embed", json={"model": self.model, "input": texts})
        r.raise_for_status()
        return r.json()["embeddings"]


class OpenAIEmbedder(Embedder):
    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"),
                                        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                                        timeout=30)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        r = await self.client.post("/embeddings", json={"model": self.model, "input": texts})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
