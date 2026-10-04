# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The blackboard is not mutated directly: it is a projection of the event log."""

from __future__ import annotations

from collections.abc import Iterable

from hydra.blackboard.state import Belief, BlackboardState, Evidence
from hydra.core.events import EventType, HydraEvent


class BlackboardProjector:
    def apply(self, state: BlackboardState, event: HydraEvent) -> BlackboardState:
        p = event.payload
        match event.type:
            case EventType.TASK_CREATED:
                state.objective = p.get("objective", "")
            case EventType.TASK_STATUS:
                state.status = p["status"]
            case EventType.ANSWER_PROPOSED:
                state.candidates.append(p)
            case EventType.TOOL_DENIED:
                state.failures.append({"type": event.type.value, **p})
                if p.get("kind") == "needs_confirmation":
                    state.pending_confirmations.append(
                        {"tool": p.get("tool"), "reason": p.get("error"), "arguments": p.get("arguments")})
            case EventType.MODEL_FAILED | EventType.TOOL_FAILED:
                state.failures.append({"type": event.type.value, **p})
            case EventType.POLICY_EVALUATED:
                state.policy = p
            case EventType.META_DECISION:
                state.meta_decisions.append(p)
            case EventType.WORLD_UPDATED:
                state.world = p.get("world", state.world)
            case EventType.SIMULATION_COMPLETED:
                state.simulations.append(p)
            case EventType.CLAIMS_ASSESSED:
                state.claims = list(p.get("claims", []))
            case EventType.PROVENANCE_RECORDED:
                state.provenance = list(p.get("records", []))
            case EventType.ARTIFACT_CREATED:
                state.artifacts.append(p)
            case EventType.RESEARCH_GRAPH_UPDATED:
                state.research_graph = p
            case EventType.COUNTERFACTUAL_ANALYZED:
                state.counterfactual = p
            case EventType.CONTEXT_COMPRESSED:
                state.compressed_context = p
            case EventType.CACHE_HIT:
                state.cache_hit = p
            case EventType.CRITIQUE_ADDED:
                state.critiques.append(p)
            case EventType.TOOL_COMPLETED:
                state.tool_results.append(p)
            case EventType.HYPOTHESIS_ADDED:
                state.hypotheses.append(p)
            case EventType.FACT_ADDED:
                state.facts.append(p)
            case EventType.MEMORY_RETRIEVED:
                state.memories.extend(p.get("items", []))
            case EventType.EVIDENCE_ADDED:
                ev = Evidence.model_validate(p)
                state.evidence[ev.id] = ev
            case EventType.BELIEF_UPDATED:
                b = Belief.model_validate(p)
                state.beliefs[b.id] = b
            case EventType.PLAN_CREATED | EventType.PLAN_REVISED | EventType.ESCALATED | EventType.RETRY_DECIDED:
                state.decisions.append({"type": event.type.value, **p})
            case EventType.VERIFICATION_COMPLETED:
                state.verification = p
                state.uncertainties = list(p.get("uncertainties", []))
            case EventType.SYNTHESIS_COMPLETED:
                state.final_answer = p.get("answer")
        return state


def replay(events: Iterable[HydraEvent]) -> BlackboardState:
    """Rebuild exactly what happened in a task from its event log."""
    projector = BlackboardProjector()
    state = BlackboardState()
    for event in events:
        projector.apply(state, event)
    return state
