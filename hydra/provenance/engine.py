# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Provenance Engine: every important claim can answer "where did this come from?".

claim
 ├─ source: document / user input / memory
 ├─ tool_result: query Y
 ├─ model: reasoner-3
 ├─ timestamp
 ├─ confidence
 └─ verification_status
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from hydra.blackboard.state import BlackboardState
from hydra.core.contracts import Claim
from hydra.verification.uncertainty import NUM, containment


class Source(BaseModel):
    type: str  # user_input | document | memory | tool_result | model | judge_fact
    ref: str
    excerpt: str = ""
    strength: float = 0.0


class ProvenanceRecord(BaseModel):
    claim_id: str
    claim: str
    sources: list[Source] = Field(default_factory=list)
    model: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: float
    verification_status: str


def _excerpt(text: str, claim: str, width: int = 240) -> str:
    nums = NUM.findall(claim)
    for n in nums:
        i = text.find(n)
        if i != -1:
            return text[max(0, i - width // 2): i + width // 2].strip()
    return text[:width].strip()


class ProvenanceEngine:
    def __init__(self, min_overlap: float = 0.3) -> None:
        self.min_overlap = min_overlap

    def build(self, claims: list[Claim], state: BlackboardState, chosen: dict, verified: bool,
              documents: dict[str, str] | None = None) -> list[ProvenanceRecord]:
        records = []
        for c in claims:
            sources: list[Source] = []
            for i, r in enumerate(state.tool_results):
                out = str(r.get("result", ""))
                s = self._support(c.text, out)
                if s >= self.min_overlap:
                    sources.append(Source(type="tool_result", ref=f"{r.get('tool')}#{i}",
                                          excerpt=_excerpt(out, c.text), strength=round(s, 3)))
            for m in state.memories:
                s = containment(c.text, m.get("text", ""))
                if s >= self.min_overlap:
                    sources.append(Source(type="memory", ref=m.get("id", "?"),
                                          excerpt=m.get("text", "")[:240], strength=round(s, 3)))
            for name, text in (documents or {}).items():
                s = self._support(c.text, text)
                if s >= self.min_overlap:
                    sources.append(Source(type="user_input" if name == "request" else "document", ref=name,
                                          excerpt=_excerpt(text, c.text), strength=round(s, 3)))
            for f in state.facts:
                s = containment(c.text, f.get("fact", ""))
                if s >= self.min_overlap:
                    sources.append(Source(type="judge_fact", ref=f.get("source", "judge"),
                                          excerpt=f.get("fact", "")[:240], strength=round(s, 3)))
            sources.append(Source(type="model", ref=chosen.get("model", "?"), strength=0.0))
            status = c.status if c.status != "supported" else ("verified" if verified else "supported")
            records.append(ProvenanceRecord(
                claim_id=c.id, claim=c.text, sources=sorted(sources, key=lambda s: -s.strength),
                model=chosen.get("model"), confidence=c.confidence, verification_status=status))
        return records

    @staticmethod
    def _support(claim: str, text: str) -> float:
        base = containment(claim, text)
        nums = set(NUM.findall(claim))
        if nums:
            hit = len(nums & set(NUM.findall(text))) / len(nums)
            base = max(base, hit)
        return base
