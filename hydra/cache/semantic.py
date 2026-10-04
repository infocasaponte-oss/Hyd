# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Semantic cache (not the KV cache): request -> semantic fingerprint -> verified previous result.

A hit requires: near-identical meaning, same execution constraints, a result that was
verified, not expired, produced without side-effect tools, and memory sources unchanged.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.contracts import HydraRequest, HydraResponse
from hydra.memory.embeddings import Embedder, cosine, tokenize
from hydra.memory.store import MemoryStore

DETERMINISTIC_TOOLS = {"python.execute", "json.validate", "search.query"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CacheEntry(BaseModel):
    key: str
    text: str
    embedding: list[float]
    constraints: str
    response: dict[str, Any]
    sources: dict[str, str] = Field(default_factory=dict)  # memory id -> text hash
    created: float = Field(default_factory=time.time)
    hits: int = 0


class SemanticCache:
    def __init__(self, embedder: Embedder, memory: MemoryStore | None = None, threshold: float = 0.97,
                 ttl_s: float = 3600, max_entries: int = 2000, min_confidence: float = 0.75) -> None:
        self.embedder = embedder
        self.memory = memory
        self.threshold = threshold
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.min_confidence = min_confidence
        self.entries: OrderedDict[str, CacheEntry] = OrderedDict()

    @staticmethod
    def fingerprint(request: HydraRequest) -> str:
        """Normalized text of the conversation (case, accents, punctuation, spacing removed)."""
        return " ".join(f"{m.role}:{' '.join(tokenize(m.content))}" for m in request.messages)

    @staticmethod
    def constraints(request: HydraRequest) -> str:
        return f"{request.mode.value}|{request.private}|{sorted(request.approved_actions)}|{len(request.images)}"

    def cacheable(self, request: HydraRequest, response: HydraResponse) -> bool:
        m = response.meta
        return (
            request.use_cache
            and not request.images
            and m.decision == "answer"
            and m.verified
            and m.confidence >= self.min_confidence
            and set(m.tools_used) <= DETERMINISTIC_TOOLS
            and not response.pending_confirmations
        )

    async def lookup(self, request: HydraRequest) -> tuple[HydraResponse, float] | None:
        if not request.use_cache or request.images:
            return None
        text = self.fingerprint(request)
        constraints = self.constraints(request)
        now = time.time()
        exact = self.entries.get(_hash(constraints + text))
        best: tuple[CacheEntry, float] | None = (exact, 1.0) if exact else None
        if best is None and self.entries:
            [emb] = await self.embedder.embed([text])
            for e in self.entries.values():
                if e.constraints != constraints:
                    continue
                s = cosine(emb, e.embedding)
                if s >= self.threshold and (best is None or s > best[1]):
                    best = (e, s)
        if best is None:
            return None
        entry, score = best
        if now - entry.created > self.ttl_s or not await self._sources_unchanged(entry):
            self.entries.pop(entry.key, None)
            return None
        entry.hits += 1
        self.entries.move_to_end(entry.key)
        resp = HydraResponse.model_validate(entry.response)
        resp.meta.cached = True
        return resp, score

    async def store(self, request: HydraRequest, response: HydraResponse, memory_ids: list[str]) -> bool:
        if not self.cacheable(request, response):
            return False
        text = self.fingerprint(request)
        constraints = self.constraints(request)
        [emb] = await self.embedder.embed([text])
        sources = {}
        if self.memory is not None:
            for mid in memory_ids:
                if item := await self.memory.get(mid):
                    sources[mid] = _hash(item.text + item.status.value)
        key = _hash(constraints + text)
        self.entries[key] = CacheEntry(key=key, text=text, embedding=emb, constraints=constraints,
                                       response=response.model_dump(mode="json"), sources=sources)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        return True

    async def _sources_unchanged(self, entry: CacheEntry) -> bool:
        if self.memory is None:
            return True
        for mid, h in entry.sources.items():
            item = await self.memory.get(mid)
            if item is None or _hash(item.text + item.status.value) != h:
                return False
        return True

    def invalidate(self) -> int:
        n = len(self.entries)
        self.entries.clear()
        return n
