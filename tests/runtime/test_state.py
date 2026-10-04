# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.contracts import TaskStatus
from hydra.runtime.state import InvalidTransition, validate_transition


def test_valid_transition():
    validate_transition(TaskStatus.CREATED, TaskStatus.ROUTING)


def test_terminal_transition_rejected():
    with pytest.raises(InvalidTransition):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.ROUTING)
