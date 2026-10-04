# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus Economy and analytics: gap detection, hard-example mining, frontier corpus,
data valuation, pruning and dataset-contribution (ablation) analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from hydra.corpus.dedup import hamming
from hydra.corpus.records import CorpusRecord, TrainingStatus
from hydra.corpus.store import CorpusStore


class DataValue(BaseModel):
    record_id: str
    novelty: float
    difficulty: float
    reuse: float
    model_improvement: float | None = None
    uniqueness: float
    estimated_value: float


class CoverageGap(BaseModel):
    capability: str
    language: str | None
    have: int
    desired: int
    deficit: int


class CorpusAnalytics:
    def __init__(self, store: CorpusStore) -> None:
        self.store = store

    def value(self, rec: CorpusRecord) -> DataValue:
        sims = [int(r.hashes["simhash"], 16) for r in self.store.records.values()
                if r.id != rec.id and r.hashes.get("simhash")]
        own = int(rec.hashes.get("simhash", "0"), 16) if rec.hashes.get("simhash") else None
        near = sum(1 for s in sims if own is not None and hamming(own, s) <= 10)
        uniqueness = 1 / (1 + near)
        difficulty = rec.difficulty if rec.difficulty is not None else (0.9 if "frontier" in rec.flags else
                                                                        0.75 if "hard" in rec.flags else 0.3)
        reuse = min(1.0, sum(1 for e in self.store.edges if e.parent_id == rec.id) / 5)
        novelty = uniqueness
        improvement = rec.metadata.get("model_improvement")
        v = 0.3 * novelty + 0.3 * difficulty + 0.15 * reuse + 0.25 * uniqueness
        if improvement is not None:
            v = 0.7 * v + 0.3 * min(1.0, max(0.0, improvement * 10))
        return DataValue(record_id=rec.id, novelty=round(novelty, 3), difficulty=round(difficulty, 3),
                         reuse=round(reuse, 3), model_improvement=improvement, uniqueness=round(uniqueness, 3),
                         estimated_value=round(v, 4))

    def mine_hard(self) -> list[str]:
        """Disagreement, failed first verification, retries -> HARD."""
        hard = []
        for r in self.store.records.values():
            if "hard" in r.flags:
                hard.append(r.id)
            elif r.record_type.value in ("contrastive", "failure") or r.metadata.get("replans", 0) > 0:
                hard.append(r.id)
        return hard

    def frontier(self) -> list[CorpusRecord]:
        """Problems no model solved well: the current limit of HYDRA."""
        return [r for r in self.store.records.values() if "frontier" in r.flags
                or (r.record_type.value == "failure" and not r.content.get("recovered", True))]

    def gaps(self, desired: dict[str, int], languages: list[str] | None = None) -> list[CoverageGap]:
        counts: Counter = Counter()
        for r in self.store.records.values():
            if r.training_status not in (TrainingStatus.CURATED, TrainingStatus.GOLD):
                continue
            for c in r.capabilities or ["general"]:
                counts[(c, r.language)] += 1
                counts[(c, None)] += 1
        out = []
        for cap, want in desired.items():
            for lang in languages or [None]:
                have = counts[(cap, lang)]
                if have < want:
                    out.append(CoverageGap(capability=cap, language=lang, have=have, desired=want, deficit=want - have))
        return sorted(out, key=lambda g: -g.deficit)

    def prune_candidates(self, min_value: float = 0.2, keep_hard: bool = True) -> list[str]:
        """Duplicate/redundant/low-value/obsolete/low-confidence curated records to archive."""
        out = []
        for r in self.store.records.values():
            if r.training_status not in (TrainingStatus.CURATED, TrainingStatus.GOLD):
                continue
            if keep_hard and ("hard" in r.flags or "frontier" in r.flags):
                continue
            if r.verification < 0.5 or self.value(r).estimated_value < min_value:
                out.append(r.id)
        return out

    def health(self) -> dict[str, Any]:
        s = self.store.stats()
        s["hard_examples"] = len(self.mine_hard())
        s["frontier"] = len(self.frontier())
        s["gold"] = s["status"].get("GOLD", 0)
        s["curated"] = s["status"].get("CURATED", 0)
        return s


class AblationResult(BaseModel):
    subset: str
    baseline: float
    without: float
    contribution: float


class ContributionAnalysis(BaseModel):
    """Dataset contribution via ablations: train/eval without subset X, measure the delta."""

    results: list[AblationResult] = Field(default_factory=list)

    def add(self, subset: str, baseline: float, without: float) -> AblationResult:
        r = AblationResult(subset=subset, baseline=baseline, without=without, contribution=round(baseline - without, 4))
        self.results.append(r)
        return r

    def ranking(self) -> list[AblationResult]:
        return sorted(self.results, key=lambda r: -r.contribution)
