# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Cognitive JIT: detect repeated cognitive workflows and propose compiling them into a
small specialist.

    Router 1B -> Reasoner 32B -> Tool -> Critic 14B -> Judge 14B     (5 calls)
      ... a million successful traces later ...
    HYDRA-Specialist-7B                                               (1 call)

HYDRA never retrains itself in production: it produces a proposal that the Factory
trains and the Lab evaluates before any promotion.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from hydra.telemetry.metrics import InferenceRun, TaskRecord


class SpecialistProposal(BaseModel):
    name: str
    task_type: str
    tools: list[str]
    examples: int
    mean_model_calls: float
    mean_confidence: float
    mean_latency_ms: float
    expected_calls_after: int = 1
    estimated_call_savings: float
    suggested_base_size: str


class CognitiveJIT:
    def __init__(self, min_examples: int = 50, min_calls: float = 3.0, min_confidence: float = 0.8) -> None:
        self.min_examples = min_examples
        self.min_calls = min_calls
        self.min_confidence = min_confidence

    def mine(self, tasks: list[TaskRecord], runs: list[InferenceRun]) -> list[SpecialistProposal]:
        calls: dict = defaultdict(int)
        for r in runs:
            calls[r.task_id] += 1
        groups: dict[tuple, list[TaskRecord]] = defaultdict(list)
        for t in tasks:
            meta = (t.final_response or {}).get("meta") or {}
            if t.status != "completed" or meta.get("decision", "answer") != "answer" or meta.get("cached"):
                continue
            key = (meta.get("task_type", "chat"), tuple(sorted(meta.get("tools_used", []))))
            groups[key].append(t)

        proposals = []
        for (task_type, tools), ts in groups.items():
            good = [t for t in ts if t.final_response["meta"].get("confidence", 0) >= self.min_confidence]
            if len(good) < self.min_examples:
                continue
            mean_calls = sum(calls.get(t.id, 1) for t in good) / len(good)
            if mean_calls < self.min_calls:
                continue
            conf = sum(t.final_response["meta"]["confidence"] for t in good) / len(good)
            lat = sum(t.final_response["meta"].get("latency_ms", 0) for t in good) / len(good)
            proposals.append(SpecialistProposal(
                name=f"hydra-{task_type}{'-' + '-'.join(x.split('.')[0] for x in tools) if tools else ''}-specialist",
                task_type=task_type, tools=list(tools), examples=len(good), mean_model_calls=round(mean_calls, 2),
                mean_confidence=round(conf, 3), mean_latency_ms=round(lat, 1),
                estimated_call_savings=round(1 - 1 / mean_calls, 3),
                suggested_base_size="1-3B" if task_type in ("chat", "tool_use") else "7B",
            ))
        return sorted(proposals, key=lambda p: -(p.examples * p.estimated_call_savings))
