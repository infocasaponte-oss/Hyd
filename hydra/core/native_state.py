# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.core.native_contracts import TaskStatus

_ALLOWED = {
    TaskStatus.CREATED: {TaskStatus.ROUTING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.ROUTING: {TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.FAILED},
    TaskStatus.PLANNING: {TaskStatus.EXECUTING, TaskStatus.FAILED},
    TaskStatus.EXECUTING: {TaskStatus.VERIFYING, TaskStatus.SYNTHESIZING, TaskStatus.FAILED},
    TaskStatus.VERIFYING: {TaskStatus.EXECUTING, TaskStatus.SYNTHESIZING, TaskStatus.FAILED},
    TaskStatus.SYNTHESIZING: {TaskStatus.CAPTURING, TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.CAPTURING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class InvalidTransition(ValueError):
    pass


def validate_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"Invalid task transition: {current} -> {target}")
