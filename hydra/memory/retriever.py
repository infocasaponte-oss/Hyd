# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hybrid retriever: embedding search + graph lookup + recent episodes + procedures -> rerank."""

from __future__ import annotations

from datetime import UTC, datetime

from hydra.memory.embeddings import Embedder
from hydra.memory.embeddings import cosine
from hydra.memory.graph import MemoryGraph
from hydra.memory.models import STATUS_WEIGHT, MemoryItem, MemoryType, MemoryStatus
from hydra.memory.store import MemoryStore


class MemoryRetriever:
    def __init__(self, store: MemoryStore, embedder: Embedder, min_score: float = 0.15) -> None:
        self.store = store
        self.embedder = embedder
        self.min_score = min_score

    async def vector_search(self, query_emb: list[float], k: int = 12) -> list[tuple[MemoryItem, float]]:
        return await self.eligible_search(query_emb, {MemoryType.SEMANTIC, MemoryType.EPISODIC}, k)

    async def eligible_search(self, embedding, types, k):
        pool = [m for m in await self.store.all() if m.memory_type in types and self.eligible(m)]
        return sorted(((m, cosine(embedding, m.embedding or [])) for m in pool),
                      key=lambda pair: pair[1], reverse=True)[:k]

    async def episode_search(self, query_emb: list[float], task_type: str, k: int = 5) -> list[tuple[MemoryItem, float]]:
        hits = await self.eligible_search(query_emb, {MemoryType.EPISODIC}, k * 3)
        same = [(m, s + 0.1) for m, s in hits if m.content.get("task_type") == task_type]
        return (same or hits)[:k]

    async def procedure_search(self, query_emb: list[float], task_type: str, k: int = 3) -> list[tuple[MemoryItem, float]]:
        hits = await self.eligible_search(query_emb, {MemoryType.PROCEDURAL}, 20)
        return [(m, s + 0.15) for m, s in hits if m.content.get("task_type") == task_type][:k]

    async def graph_search(self, query: str) -> list[tuple[MemoryItem, float]]:
        semantic = [m for m in await self.store.all(MemoryType.SEMANTIC) if self.eligible(m)]
        graph = MemoryGraph.build(semantic)
        by_text = {m.text.lower(): m for m in semantic}
        found: list[tuple[MemoryItem, float]] = []
        for node in graph.mentioned(query):
            for s, p, o in graph.neighbors(node):
                if item := by_text.get(f"{s} {p} {o}".lower()):
                    found.append((item, 0.6))
        return found

    @staticmethod
    def eligible(item):
        return (item.status not in (MemoryStatus.UNVERIFIED, MemoryStatus.CONFLICT)
                and not item.content.get("revoked")
                and item.content.get("split") not in ("test", "reserved_test", "dev", "cal_prob", "cal_policy"))

    @staticmethod
    def merge(*groups: list[tuple[MemoryItem, float]]) -> list[tuple[MemoryItem, float]]:
        best: dict[str, tuple[MemoryItem, float]] = {}
        for group in groups:
            for item, score in group:
                if item.id not in best or score > best[item.id][1]:
                    best[item.id] = (item, score)
        return list(best.values())

    @staticmethod
    def rerank(merged: list[tuple[MemoryItem, float]]) -> list[tuple[MemoryItem, float]]:
        now = datetime.now(UTC)

        def final(pair: tuple[MemoryItem, float]) -> float:
            item, sim = pair
            age_days = (now - item.created_at).total_seconds() / 86400
            recency = 1 / (1 + age_days / 30)
            return 0.55 * sim + 0.15 * item.confidence + 0.20 * STATUS_WEIGHT[item.status] + 0.10 * recency

        return sorted(((i, final((i, s))) for i, s in merged), key=lambda x: x[1], reverse=True)

    async def retrieve(self, query: str, task_type: str, k: int = 8) -> list[tuple[MemoryItem, float]]:
        [emb] = await self.embedder.embed([query])
        semantic = await self.vector_search(emb)
        episodes = await self.episode_search(emb, task_type)
        procedures = await self.procedure_search(emb, task_type)
        graph = await self.graph_search(query)
        merged = [(i, s) for i, s in self.merge(semantic, episodes, procedures, graph)
                  if s >= self.min_score and self.eligible(i)]
        ranked = self.rerank(merged)[:k]
        await self.store.touch([i.id for i, _ in ranked])
        return ranked

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Adapter for the ``search.query`` tool."""
        ranked = await self.retrieve(query, task_type="", k=limit)
        return [{"text": i.text, "type": i.memory_type.value, "status": i.status.value,
                 "confidence": round(i.confidence, 3), "score": round(s, 3)} for i, s in ranked]
