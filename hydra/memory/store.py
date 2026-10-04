# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from hydra.memory.embeddings import cosine
from hydra.memory.models import MemoryItem, MemoryStatus, MemoryType


class MemoryStore(ABC):
    @abstractmethod
    async def save(self, item: MemoryItem) -> None: ...

    async def save_many(self, items: list[MemoryItem]) -> None:
        for item in items:
            await self.save(item)

    @abstractmethod
    async def get(self, item_id: str) -> MemoryItem | None: ...

    @abstractmethod
    async def all(self, memory_type: MemoryType | None = None) -> list[MemoryItem]: ...

    async def search(
        self,
        embedding: list[float],
        memory_types: set[MemoryType] | None = None,
        k: int = 10,
    ) -> list[tuple[MemoryItem, float]]:
        pool = [m for m in await self.all() if memory_types is None or m.memory_type in memory_types]
        scored = [(m, cosine(embedding, m.embedding or [])) for m in pool]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    @abstractmethod
    async def touch(self, ids: list[str]) -> None: ...

    async def close(self) -> None:
        return None


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self.items: dict[str, MemoryItem] = {}

    async def save(self, item: MemoryItem) -> None:
        self.items[item.id] = item

    async def get(self, item_id: str) -> MemoryItem | None:
        return self.items.get(item_id)

    async def all(self, memory_type: MemoryType | None = None) -> list[MemoryItem]:
        return [m for m in self.items.values() if memory_type is None or m.memory_type == memory_type]

    async def touch(self, ids: list[str]) -> None:
        now = datetime.now(UTC)
        for i in ids:
            if i in self.items:
                self.items[i].last_accessed_at = now


class PostgresMemoryStore(MemoryStore):
    """PostgreSQL-backed store (see sql/schema.sql). Vector search is done over the
    most recent rows in Python; switch the column to pgvector for large corpora."""

    def __init__(self, pool) -> None:
        self.pool = pool

    async def save(self, item: MemoryItem) -> None:
        await self.pool.execute(
            """
            INSERT INTO memories (id, memory_type, content, text, confidence, status, importance,
                                  embedding, conflicts_with, created_at, last_accessed_at)
            VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content, text = EXCLUDED.text, confidence = EXCLUDED.confidence,
                status = EXCLUDED.status, importance = EXCLUDED.importance, embedding = EXCLUDED.embedding,
                conflicts_with = EXCLUDED.conflicts_with, last_accessed_at = EXCLUDED.last_accessed_at
            """,
            item.id, item.memory_type.value, json.dumps(item.content), item.text, item.confidence,
            item.status.value, item.importance, item.embedding, item.conflicts_with,
            item.created_at, item.last_accessed_at,
        )

    @staticmethod
    def _row(r) -> MemoryItem:
        return MemoryItem(
            id=str(r["id"]), memory_type=MemoryType(r["memory_type"]), content=json.loads(r["content"]),
            text=r["text"], confidence=r["confidence"] or 0.0, status=MemoryStatus(r["status"]),
            importance=r["importance"] or 0.0, embedding=list(r["embedding"]) if r["embedding"] else None,
            conflicts_with=list(r["conflicts_with"] or []), created_at=r["created_at"],
            last_accessed_at=r["last_accessed_at"],
        )

    async def get(self, item_id: str) -> MemoryItem | None:
        r = await self.pool.fetchrow("SELECT * FROM memories WHERE id = $1", item_id)
        return self._row(r) if r else None

    async def all(self, memory_type: MemoryType | None = None, limit: int = 5000) -> list[MemoryItem]:
        if memory_type is None:
            rows = await self.pool.fetch("SELECT * FROM memories ORDER BY created_at DESC LIMIT $1", limit)
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM memories WHERE memory_type = $1 ORDER BY created_at DESC LIMIT $2",
                memory_type.value, limit,
            )
        return [self._row(r) for r in rows]

    async def touch(self, ids: list[str]) -> None:
        if ids:
            await self.pool.execute("UPDATE memories SET last_accessed_at = now() WHERE id = ANY($1::uuid[])", ids)
