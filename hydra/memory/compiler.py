# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Memory compiler: execution history -> candidates -> dedupe -> importance -> validate -> persist.

Importance:  I = 0.30 R + 0.25 N + 0.20 U + 0.15 C + 0.10 F
(relevance, novelty, utility, confidence, expected future reuse).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from hydra.memory.embeddings import Embedder, cosine
from hydra.memory.models import (
    Episode,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    Procedure,
    SemanticFact,
)
from hydra.memory.store import MemoryStore

IMPORTANCE_THRESHOLD = 0.7

# Predicates that admit a single value: two different objects are a conflict.
FUNCTIONAL = {"listens_on", "version", "owner", "located_in"}

_SUBJ = r"(?:el servicio |el proyecto |la base de datos |the service |the project |service |project )?(?P<s>[\w\-.]+)"
PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(_SUBJ + r" (?:usa|utiliza|uses|escucha en|listens on) (?:el |the )?(?:puerto|port) (?P<o>\d{2,5})", re.I), "listens_on"),
    (re.compile(_SUBJ + r" (?:depende de|depends on) (?:el |la |the )?(?P<o>[\w\-.]+)", re.I), "depends_on"),
    (re.compile(_SUBJ + r" (?:usa|utiliza|uses) (?:el |la |the )?(?P<o>[\w\-.]+)", re.I), "uses"),
    (re.compile(_SUBJ + r" (?:está en la versión|is on version|version) (?P<o>v?\d+(?:\.\d+)*)", re.I), "version"),
]

STOP_SUBJECTS = {"yo", "tu", "tú", "i", "you", "we", "nosotros", "it", "esto", "this", "que", "which", "and", "y"}


class OutcomeRecord(BaseModel):
    task_type: str
    objective: str
    answer: str
    success: bool
    verified: bool
    confidence: float
    complexity: float
    strategy: list[str]
    tools: list[str]


Extractor = Callable[[str], Awaitable[list[SemanticFact]]]


def extract_facts(text: str, confidence: float = 0.6) -> list[SemanticFact]:
    facts: list[SemanticFact] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern, predicate in PATTERNS:
        for m in pattern.finditer(text):
            s, o = m.group("s").strip(" ."), m.group("o").strip(" .")
            if s.lower() in STOP_SUBJECTS or not o:
                continue
            key = (s.lower(), predicate, o.lower())
            # 'uses port N' also matches the generic 'uses X' pattern
            if predicate == "uses" and o.lower() in ("puerto", "port"):
                continue
            if key in seen:
                continue
            seen.add(key)
            facts.append(SemanticFact(subject=s, predicate=predicate, object=o, confidence=confidence))
    return facts


def importance(r: float, n: float, u: float, c: float, f: float) -> float:
    return 0.30 * r + 0.25 * n + 0.20 * u + 0.15 * c + 0.10 * f


class MemoryCompiler:
    def __init__(self, store: MemoryStore, embedder: Embedder, extractor: Extractor | None = None,
                 threshold: float = IMPORTANCE_THRESHOLD) -> None:
        self.store = store
        self.embedder = embedder
        self.extractor = extractor
        self.threshold = threshold

    async def _novelty(self, item: MemoryItem, existing: list[MemoryItem]) -> float:
        same = [e for e in existing if e.memory_type == item.memory_type and e.embedding]
        if not same or not item.embedding:
            return 1.0
        return 1.0 - max(cosine(item.embedding, e.embedding) for e in same)

    async def extract_candidates(self, outcome: OutcomeRecord) -> list[MemoryItem]:
        items: list[MemoryItem] = []

        # Facts stated by the user are SUPPORTED (a real source); facts only asserted
        # by a model stay UNVERIFIED until evidence confirms them.
        for fact in extract_facts(outcome.objective, confidence=0.7):
            items.append(MemoryItem.from_fact(fact, status=MemoryStatus.SUPPORTED))
        if self.extractor is not None:
            for fact in await self.extractor(outcome.answer):
                fact.confidence = min(fact.confidence, 0.5)
                items.append(MemoryItem.from_fact(fact, status=MemoryStatus.UNVERIFIED))

        episode = Episode(
            task_type=outcome.task_type,
            summary=outcome.objective[:300],
            strategy=outcome.strategy,
            outcome=outcome.answer[:500],
            success=outcome.success,
            confidence=outcome.confidence,
        )
        items.append(MemoryItem.from_episode(
            episode, status=MemoryStatus.VERIFIED if outcome.verified else MemoryStatus.UNVERIFIED,
        ))

        if outcome.tools:
            # Failed runs still count: they lower the success rate of a known procedure.
            proc = Procedure(
                name=f"{outcome.task_type}:" + "+".join(dict.fromkeys(outcome.tools)),
                task_type=outcome.task_type,
                steps=outcome.strategy,
                success_rate=1.0 if outcome.success else 0.0,
            )
            items.append(MemoryItem.from_procedure(proc, status=MemoryStatus.SUPPORTED))

        embeddings = await self.embedder.embed([i.text for i in items])
        for item, emb in zip(items, embeddings):
            item.embedding = emb
        return items

    def score(self, item: MemoryItem, outcome: OutcomeRecord, novelty: float) -> float:
        match item.memory_type:
            case MemoryType.SEMANTIC:
                has_specifics = bool(re.search(r"\d|[A-Z_\-.]", item.content.get("object", "")))
                return importance(1.0, novelty, 0.7, item.confidence, 0.9 if has_specifics else 0.7)
            case MemoryType.EPISODIC:
                utility = outcome.complexity if outcome.success else outcome.complexity * 0.8
                return importance(outcome.complexity, novelty, utility, outcome.confidence, 0.6)
            case MemoryType.PROCEDURAL:
                return importance(0.8, max(novelty, 0.5), 0.9, outcome.confidence, 0.9)
        return 0.0

    async def compile(self, outcome: OutcomeRecord) -> list[MemoryItem]:
        existing = await self.store.all()
        candidates = await self.extract_candidates(outcome)
        stored: list[MemoryItem] = []

        for item in candidates:
            if item.memory_type == MemoryType.SEMANTIC and await self._merge_fact(item, existing):
                continue
            if item.memory_type == MemoryType.PROCEDURAL:
                if await self._merge_procedure(item, outcome, existing):
                    continue
                if not (outcome.success and outcome.confidence >= 0.7):
                    continue  # only proven procedures are learned
            item.importance = round(self.score(item, outcome, await self._novelty(item, existing)), 4)
            if item.importance < self.threshold:
                continue
            if item.memory_type == MemoryType.SEMANTIC:
                await self._mark_conflicts(item, existing)
            await self.store.save(item)
            existing.append(item)
            stored.append(item)
        return stored

    async def _merge_fact(self, item: MemoryItem, existing: list[MemoryItem]) -> bool:
        """Dedupe: the same fact seen again gains support instead of being duplicated."""
        c = item.content
        for e in existing:
            if e.memory_type != MemoryType.SEMANTIC:
                continue
            ec = e.content
            if (ec["subject"].lower(), ec["predicate"], ec["object"].lower()) == (
                c["subject"].lower(), c["predicate"], c["object"].lower()
            ):
                ec["source_count"] = ec.get("source_count", 1) + 1
                e.confidence = min(0.99, e.confidence + (1 - e.confidence) * 0.3)
                ec["confidence"] = e.confidence
                if e.status == MemoryStatus.UNVERIFIED and ec["source_count"] >= 2:
                    e.status = MemoryStatus.SUPPORTED
                await self.store.save(e)
                await self._try_resolve(e, existing)
                return True
        return False

    async def _mark_conflicts(self, item: MemoryItem, existing: list[MemoryItem]) -> None:
        """Conflicting facts coexist, marked as conflict, until evidence resolves them."""
        c = item.content
        if c["predicate"] not in FUNCTIONAL:
            return
        for e in existing:
            if e.memory_type != MemoryType.SEMANTIC or e.content.get("valid_until"):
                continue
            ec = e.content
            if (ec["subject"].lower(), ec["predicate"]) == (c["subject"].lower(), c["predicate"]) \
                    and ec["object"].lower() != c["object"].lower():
                item.status = MemoryStatus.CONFLICT
                item.conflicts_with.append(e.id)
                if item.id not in e.conflicts_with:
                    e.conflicts_with.append(item.id)
                e.status = MemoryStatus.CONFLICT
                await self.store.save(e)

    async def _try_resolve(self, fact: MemoryItem, existing: list[MemoryItem]) -> None:
        if fact.status != MemoryStatus.CONFLICT and not fact.conflicts_with:
            return
        rivals = [e for e in existing if e.id in fact.conflicts_with]
        mine = fact.content.get("source_count", 1)
        if rivals and all(mine >= r.content.get("source_count", 1) + 2 for r in rivals):
            await self.resolve_conflict(fact.id)

    async def resolve_conflict(self, winner_id: str) -> MemoryItem | None:
        winner = await self.store.get(winner_id)
        if winner is None:
            return None
        now = datetime.now(UTC).isoformat()
        for rid in winner.conflicts_with:
            if loser := await self.store.get(rid):
                loser.content["valid_until"] = now
                loser.status = MemoryStatus.CONFLICT
                await self.store.save(loser)
        winner.status = MemoryStatus.VERIFIED
        winner.conflicts_with = []
        await self.store.save(winner)
        return winner

    async def _merge_procedure(self, item: MemoryItem, outcome: OutcomeRecord, existing: list[MemoryItem]) -> bool:
        for e in existing:
            if e.memory_type == MemoryType.PROCEDURAL and e.content["name"] == item.content["name"]:
                runs = e.content.get("runs", 1) + 1
                rate = e.content["success_rate"] + ((1.0 if outcome.success else 0.0) - e.content["success_rate"]) / runs
                e.content.update(runs=runs, success_rate=round(rate, 4))
                e.confidence = rate
                await self.store.save(e)
                return True
        return False
