# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Explicit task state machine."""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    CREATED = "created"
    ROUTING = "routing"
    RETRIEVING = "retrieving"
    PLANNING = "planning"
    EXECUTING = "executing"
    RETRYING = "retrying"
    ESCALATING = "escalating"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    CAPTURING = "capturing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


S = TaskStatus

TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    S.CREATED: {S.ROUTING, S.COMPLETED, S.FAILED},  # COMPLETED: semantic cache hit / policy refusal
    S.ROUTING: {S.RETRIEVING, S.PLANNING, S.COMPLETED, S.FAILED},  # COMPLETED: metacognition asks the user
    S.RETRIEVING: {S.PLANNING, S.COMPLETED, S.FAILED},
    S.PLANNING: {S.EXECUTING, S.FAILED},
    S.EXECUTING: {S.VERIFYING, S.RETRYING, S.ESCALATING, S.PLANNING, S.FAILED},
    S.RETRYING: {S.EXECUTING, S.ESCALATING, S.FAILED},
    S.ESCALATING: {S.PLANNING, S.EXECUTING, S.FAILED},
    S.VERIFYING: {S.SYNTHESIZING, S.ESCALATING, S.PLANNING, S.FAILED},
    S.SYNTHESIZING: {S.CAPTURING, S.COMPLETED, S.FAILED},
    S.CAPTURING: {S.COMPLETED, S.FAILED},
    S.COMPLETED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
}


class InvalidTransition(RuntimeError):
    pass


class TaskStateMachine:
    def __init__(self) -> None:
        self.status = TaskStatus.CREATED
        self.history: list[TaskStatus] = [self.status]

    def to(self, new: TaskStatus) -> TaskStatus:
        if new == TaskStatus.CANCELLED and not self.terminal:
            self.status = new
            self.history.append(new)
            return new
        if new not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status.value} -> {new.value}")
        self.status = new
        self.history.append(new)
        return new

    @property
    def terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
