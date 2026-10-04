# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Counterfactual Engine: after a task, ask what would have happened otherwise.

- would another (cheaper) model have produced the same answer?
- were three reasoners really necessary?
- could we have stopped earlier?
- which tool actually contributed information?
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from hydra.core.events import EventType, HydraEvent
from hydra.registry.registry import ModelRegistry
from hydra.verification.consensus import pair_agreement
from hydra.verification.uncertainty import NUM, containment


class ToolContribution(BaseModel):
    tool: str
    contributed: bool
    overlap: float


class CounterfactualReport(BaseModel):
    model_calls: int
    failed_calls: int
    ensemble_size: int
    ensemble_necessary: bool | None = None
    cheaper_alternative: str | None = None
    early_stop_possible: bool = False
    wasted_calls: int = 0
    estimated_savings_calls: int = 0
    tool_contributions: list[ToolContribution] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)


class CounterfactualEngine:
    def __init__(self, registry: ModelRegistry, agree: float = 0.8) -> None:
        self.registry = registry
        self.agree = agree

    def analyze(self, events: list[HydraEvent], chosen: dict, answer: str, accept_confidence: float
                ) -> CounterfactualReport:
        calls = [e for e in events if e.type == EventType.MODEL_COMPLETED]
        failed = [e for e in events if e.type == EventType.MODEL_FAILED]
        candidates = [e.payload for e in events if e.type == EventType.ANSWER_PROPOSED]
        verifications = [e.payload for e in events if e.type == EventType.VERIFICATION_COMPLETED]
        r = CounterfactualReport(model_calls=len(calls), failed_calls=len(failed), ensemble_size=len(candidates))

        # 1. Was the ensemble necessary?
        if len(candidates) > 1:
            agreeing = [c for c in candidates
                        if pair_agreement(c.get("answer", ""), chosen.get("answer", "")) >= self.agree]
            r.ensemble_necessary = len(agreeing) < len(candidates)
            if not r.ensemble_necessary:
                r.estimated_savings_calls += len(candidates) - 1
                r.insights.append(f"all {len(candidates)} candidates agreed: one model would have sufficed")

            # 2. Would a cheaper model have given the same answer?
            chosen_model = self.registry.models.get(chosen.get("model", ""))
            if chosen_model is not None:
                cheaper = [self.registry.models[c["model"]] for c in agreeing
                           if c.get("model") in self.registry.models
                           and self.registry.models[c["model"]].tier < chosen_model.tier]
                if cheaper:
                    best = min(cheaper, key=lambda m: m.tier)
                    r.cheaper_alternative = best.id
                    r.insights.append(f"{best.id} (tier {best.tier}) matched the answer of "
                                      f"{chosen_model.id} (tier {chosen_model.tier})")

        # 3. Could we have stopped earlier?
        if len(verifications) > 1:
            first = verifications[0]
            if first.get("passed") and first.get("confidence", 0) >= accept_confidence - 0.05:
                r.early_stop_possible = True
                later_calls = self._calls_after(events, first_verification=True)
                r.estimated_savings_calls += later_calls
                r.insights.append(f"first verification already passed (confidence "
                                  f"{first.get('confidence'):.2f}); {later_calls} later calls were optional")

        # 4. Which tool contributed?
        for e in events:
            if e.type == EventType.TOOL_COMPLETED:
                out = str(e.payload.get("result", ""))
                nums = set(NUM.findall(answer)) & set(NUM.findall(out))
                overlap = max(containment(out[:2000], answer), 1.0 if nums else 0.0)
                r.tool_contributions.append(ToolContribution(
                    tool=e.payload.get("tool", "?"), contributed=overlap >= 0.3, overlap=round(overlap, 3)))
        useless = [t.tool for t in r.tool_contributions if not t.contributed]
        if useless:
            r.insights.append("tools without visible contribution: " + ", ".join(sorted(set(useless))))

        r.wasted_calls = len(failed)
        return r

    @staticmethod
    def _calls_after(events: list[HydraEvent], first_verification: bool) -> int:
        seen = False
        n = 0
        for e in events:
            if e.type == EventType.VERIFICATION_COMPLETED and not seen:
                seen = True
                continue
            if seen and e.type == EventType.MODEL_COMPLETED:
                n += 1
        return n


class CounterfactualStats:
    """Aggregated insights across tasks (fed to the Lab and the learned router)."""

    def __init__(self) -> None:
        self.tasks = 0
        self.unnecessary_ensembles = 0
        self.cheaper: dict[str, int] = defaultdict(int)
        self.early_stops = 0
        self.savings_calls = 0

    def add(self, r: CounterfactualReport) -> None:
        self.tasks += 1
        self.unnecessary_ensembles += int(r.ensemble_necessary is False)
        if r.cheaper_alternative:
            self.cheaper[r.cheaper_alternative] += 1
        self.early_stops += int(r.early_stop_possible)
        self.savings_calls += r.estimated_savings_calls

    def summary(self) -> dict:
        return {"tasks": self.tasks, "unnecessary_ensembles": self.unnecessary_ensembles,
                "cheaper_alternatives": dict(self.cheaper), "early_stops_possible": self.early_stops,
                "estimated_savings_calls": self.savings_calls}
