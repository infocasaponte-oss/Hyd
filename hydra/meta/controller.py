# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Metacognitive Controller ("System 3"): reasons about how the system is reasoning.

    do I know enough?   should I search?   should I execute?   should I ask?
    should I verify?    should I use another model?          should I stop?
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from hydra.core.budget import BudgetTracker
from hydra.core.contracts import ExecutionMode, HydraRequest, RoutingDecision, TaskType
from hydra.core.termination import TerminationPolicy, TerminationState


class MetaAction(str, Enum):
    PROCEED = "proceed"
    ASK = "ask"
    SEARCH = "search"
    EXECUTE = "execute"
    VERIFY_CLAIMS = "verify_claims"
    ESCALATE = "escalate"
    ANSWER = "answer"
    STOP = "stop"


class MetaDecision(BaseModel):
    action: MetaAction
    reason: str
    question: str | None = None
    signals: dict = Field(default_factory=dict)


DEICTIC = re.compile(r"(?i)^\s*(arr[eé]glalo|hazlo|haz eso|corr[ií]gelo|esto|eso|fix it|do it|this|that|"
                     r"sigue|continue|mejóralo|improve it)\W*$")


class MetacognitiveController:
    def __init__(self, termination: TerminationPolicy | None = None, accept_confidence: float = 0.72,
                 claim_threshold: float = 0.6) -> None:
        self.termination = termination or TerminationPolicy()
        self.accept_confidence = accept_confidence
        self.claim_threshold = claim_threshold

    def before(self, request: HydraRequest, route: RoutingDecision) -> MetaDecision:
        """Do I have enough to start? Otherwise ask one precise question."""
        text = request.last_user_text.strip()
        has_history = len(request.messages) > 1
        if not request.images and not has_history and (len(text) < 3 or DEICTIC.match(text)):
            return MetaDecision(
                action=MetaAction.ASK, reason="request refers to missing context",
                question=("¿A qué te refieres exactamente? Comparte el contenido (código, texto o archivo) "
                          "y el resultado que esperas."))
        if route.task_type == TaskType.RESEARCH and request.mode in (ExecutionMode.DEEP, ExecutionMode.MAX):
            return MetaDecision(action=MetaAction.SEARCH, reason="deep research: decompose into a research graph")
        return MetaDecision(action=MetaAction.PROCEED, reason="enough information to start")

    def after_verification(
        self,
        *,
        confidence: float,
        verified: bool,
        passed: bool,
        route: RoutingDecision,
        budget: BudgetTracker,
        tools_used: bool,
        tools_available: bool,
        uncertain_claims: int,
        claims_checked: bool,
        can_escalate: bool,
    ) -> MetaDecision:
        signals = {"confidence": confidence, "verified": verified, "passed": passed,
                   "uncertain_claims": uncertain_claims, "budget": budget.snapshot()}
        stop, reason = self.termination.should_stop(TerminationState(
            confidence=confidence,
            budget_exhausted=budget.exhausted,
            max_steps_reached=budget.max_steps_reached,
            goal_satisfied=passed and confidence >= self.accept_confidence and uncertain_claims == 0,
        ))
        if stop:
            return MetaDecision(action=MetaAction.ANSWER, reason=f"stop: {reason}", signals=signals)

        # Localised doubt: investigate only the uncertain claims, not the whole problem.
        if passed and uncertain_claims and not claims_checked and budget.can_call_model():
            return MetaDecision(action=MetaAction.VERIFY_CLAIMS,
                                reason=f"{uncertain_claims} uncertain claim(s)", signals=signals)

        # Unverified code: run it before trusting it.
        if (route.task_type == TaskType.CODING and tools_available and not tools_used
                and not verified and budget.can_call_tool() and can_escalate):
            return MetaDecision(action=MetaAction.EXECUTE, reason="code answer not executed yet", signals=signals)

        if (not passed or confidence < self.accept_confidence) and can_escalate:
            return MetaDecision(action=MetaAction.ESCALATE, reason="low confidence or failed verification",
                                signals=signals)
        return MetaDecision(action=MetaAction.ANSWER, reason="best effort within budget", signals=signals)
