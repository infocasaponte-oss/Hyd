# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Cognitive blackboard: the shared state every worker reads and writes deltas to."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    id: str
    claim_id: str
    source_type: str  # "tool" | "model" | "critic" | "memory" | "test"
    source_ref: str
    strength: float = Field(ge=0, le=1)
    supports: bool


class Belief(BaseModel):
    id: str
    statement: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class BlackboardState(BaseModel):
    objective: str = ""

    facts: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    critiques: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)

    evidence: dict[str, Evidence] = Field(default_factory=dict)
    beliefs: dict[str, Belief] = Field(default_factory=dict)

    verification: dict[str, Any] | None = None
    final_answer: str | None = None
    status: str = "created"

    policy: dict[str, Any] | None = None
    meta_decisions: list[dict[str, Any]] = Field(default_factory=list)
    world: dict[str, Any] = Field(default_factory=dict)
    simulations: list[dict[str, Any]] = Field(default_factory=list)
    pending_confirmations: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    research_graph: dict[str, Any] | None = None
    counterfactual: dict[str, Any] | None = None
    compressed_context: dict[str, Any] | None = None
    cache_hit: dict[str, Any] | None = None

    @property
    def models_used(self) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.candidates:
            if c.get("model"):
                seen[c["model"]] = None
        for c in self.critiques:
            if c.get("model"):
                seen[c["model"]] = None
        return list(seen)

    @property
    def tools_used(self) -> list[str]:
        return list(dict.fromkeys(r["tool"] for r in self.tool_results if "tool" in r))

    def best_candidate(self) -> dict[str, Any] | None:
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.get("score", 0.0))
