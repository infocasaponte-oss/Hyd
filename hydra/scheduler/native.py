# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.native_contracts import HydraTask, Route, TaskType


class StepKind(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    VERIFY = "verify"


class PlanStep(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: StepKind
    capability: str
    instruction: str
    depends_on: list[UUID] = Field(default_factory=list)
    side_effects: bool = False


class ExecutionPlan(BaseModel):
    task_id: UUID
    steps: list[PlanStep]


class Planner:
    def build(self, task: HydraTask, route: Route) -> ExecutionPlan:
        if route.task_type in {TaskType.CHAT, TaskType.TRANSLATION, TaskType.REASONING}:
            model = PlanStep(
                kind=StepKind.MODEL,
                capability=route.capability,
                instruction=task.goal,
            )
            steps = [model]
            if route.needs_verification:
                steps.append(
                    PlanStep(
                        kind=StepKind.VERIFY,
                        capability="verify.text",
                        instruction="Verify the model result conservatively.",
                        depends_on=[model.id],
                    )
                )
            return ExecutionPlan(task_id=task.id, steps=steps)

        # Coding/research plans are deliberately non-executable until sandbox/tools land.
        return ExecutionPlan(
            task_id=task.id,
            steps=[
                PlanStep(
                    kind=StepKind.TOOL,
                    capability=route.capability,
                    instruction=task.goal,
                    side_effects=True,
                )
            ],
        )
