# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Knowing when to stop thinking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TerminationState:
    confidence: float
    budget_exhausted: bool
    max_steps_reached: bool
    goal_satisfied: bool


class TerminationPolicy:
    def __init__(self, confidence_threshold: float = 0.92) -> None:
        self.confidence_threshold = confidence_threshold

    def should_stop(self, state: TerminationState) -> tuple[bool, str]:
        if state.confidence >= self.confidence_threshold:
            return True, "confidence"
        if state.budget_exhausted:
            return True, "budget"
        if state.max_steps_reached:
            return True, "max_steps"
        if state.goal_satisfied:
            return True, "goal"
        return False, ""
