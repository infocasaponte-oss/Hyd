# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.registry.native import ModelRegistry
from hydra.core.inference_budget import ModelCallBudgetExceeded, release_model_calls, reserve_model_calls
from hydra.scheduler.native import ExecutionPlan, StepKind
from hydra.providers.local_llm import LocalLLM
from hydra.verification.verifier import TextVerification as VerificationResult
from hydra.verification.verifier import Verifier


class UnsafePlan(RuntimeError):
    pass


@dataclass
class ExecutionOutput:
    answer: str
    model_id: str
    verification: VerificationResult | None


class Executor:
    def __init__(
        self,
        llm: LocalLLM,
        registry: ModelRegistry,
        verifier: Verifier,
    ):
        self.llm = llm
        self.registry = registry
        self.verifier = verifier

    async def execute(
        self, plan: ExecutionPlan, max_tokens: int, *, max_model_calls: int | None = None
    ) -> ExecutionOutput:
        if any(step.side_effects or step.kind == StepKind.TOOL for step in plan.steps):
            raise UnsafePlan("Tool/side-effect execution requires HYDRA Sandbox")

        model_steps = sum(step.kind == StepKind.MODEL for step in plan.steps)
        if max_model_calls is not None and model_steps > max_model_calls:
            raise ModelCallBudgetExceeded("Execution plan exceeds model-call budget")

        answer = ""
        model_id = ""
        verification = None

        # The shared budget may already be partly spent by physical/shadow calls: reserve the
        # whole plan now so it is rejected before any inference instead of midway.
        reserved = reserve_model_calls(model_steps)
        attempted = 0
        try:
            for step in plan.steps:
                if step.kind == StepKind.MODEL:
                    model = self.registry.resolve(step.capability, local_only=True)
                    model_id = model.model_id
                    attempted += 1  # a failed attempt still consumes its unit
                    answer = await self.llm.chat(
                        [{"role": "user", "content": step.instruction}],
                        max_tokens=max_tokens,
                    )
                elif step.kind == StepKind.VERIFY:
                    verification = self.verifier.verify_text(answer)
        finally:
            release_model_calls(max(0, reserved - attempted))

        return ExecutionOutput(answer, model_id, verification)
