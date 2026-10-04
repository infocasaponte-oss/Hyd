# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Budget-aware, re-entrant planner.

simple -> 1 model (cheapest adequate; escalates if unsure)
medium -> specialist + critic
hard   -> ensemble + judge   (risk > .9: ensemble + critic + judge)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from hydra.core.budget import CognitiveBudget
from hydra.core.contracts import ExecutionMode, HydraRequest, RoutingDecision
from hydra.core.errors import RetryAction
from hydra.registry.models import ModelProfile
from hydra.core.native_contracts import HydraTask, Route
from hydra.scheduler.native import ExecutionPlan as NativeExecutionPlan, Planner as NativePlanner


class ExecutionStep(BaseModel):
    worker: str  # reasoner | coder | critic | judge | research
    models: list[str]
    parallel: bool = False
    speculative: bool = False
    use_tools: bool = False


class ExecutionPlan(BaseModel):
    strategy: str
    steps: list[ExecutionStep]
    notes: list[str] = Field(default_factory=list)

    @property
    def generation_steps(self) -> list[ExecutionStep]:
        return [s for s in self.steps if s.worker in ("reasoner", "coder")]


class NoModelAvailable(RuntimeError):
    pass


ADEQUATE_QUALITY = 0.6


class Planner:
    def create_native(self, task: HydraTask, route: Route) -> NativeExecutionPlan:
        """Preserve the published native DAG, including non-executable tool steps."""
        return NativePlanner().build(task, route)

    def create(
        self,
        route: RoutingDecision,
        ranked_models: list[ModelProfile],
        budget: CognitiveBudget,
        request: HydraRequest,
        tools_available: bool = True,
    ) -> ExecutionPlan:
        if not ranked_models:
            raise NoModelAvailable("no model satisfies the constraints of this request")

        primary = ranked_models[0]
        use_tools = route.requires_tools and tools_available and primary.capabilities.tools >= 0.5
        gen = "coder" if use_tools else "reasoner"
        critic_model = self._independent(primary, ranked_models)

        if budget.max_model_calls <= 1:
            return ExecutionPlan(strategy="single", steps=[
                ExecutionStep(worker=gen, models=[primary.id], use_tools=use_tools)])

        if route.complexity < 0.5 and not route.requires_verification:
            cheap = self._cheapest_adequate(route, ranked_models, request)
            return ExecutionPlan(strategy="cascade", steps=[
                ExecutionStep(worker=gen, models=[cheap.id], use_tools=use_tools)],
                notes=["start cheap; escalate if verification or confidence is low"])

        if route.complexity < 0.8 and route.risk <= 0.9 and route.desired_parallelism <= 1:
            steps = [ExecutionStep(worker=gen, models=[primary.id], use_tools=use_tools)]
            if budget.max_model_calls >= 2:
                steps.append(ExecutionStep(worker="critic", models=[critic_model.id]))
            return ExecutionPlan(strategy="specialist+critic", steps=steps)

        # Hard / risky: ensemble. Reserve calls for critic and judge.
        width = min(
            max(route.desired_parallelism, 2),
            budget.max_parallel_workers,
            len(ranked_models),
            max(1, budget.max_model_calls - 2),
        )
        ensemble = [m.id for m in ranked_models[:width]]
        steps = [ExecutionStep(worker=gen, models=ensemble, parallel=len(ensemble) > 1,
                               speculative=request.mode != ExecutionMode.MAX and len(ensemble) > 2,
                               use_tools=use_tools)]
        if len(ensemble) > 1:
            steps.append(ExecutionStep(worker="judge", models=[primary.id]))
        if (route.risk > 0.9 or request.mode == ExecutionMode.MAX) and budget.max_model_calls >= width + 2:
            steps.append(ExecutionStep(worker="critic", models=[critic_model.id]))
        return ExecutionPlan(strategy="ensemble+judge", steps=steps)

    def replan(
        self,
        previous: ExecutionPlan,
        action: RetryAction,
        route: RoutingDecision,
        ranked_models: list[ModelProfile],
        budget: CognitiveBudget,
        request: HydraRequest,
    ) -> ExecutionPlan:
        """Re-entrant planning: new evidence (failures) produces a new plan."""
        tools = action != RetryAction.REPLAN_WITHOUT_TOOL
        plan = self.create(route, ranked_models, budget, request, tools_available=tools)
        plan.notes.append(f"replanned after {action.value} (previous: {previous.strategy})")
        return plan

    def escalate(self, target: ModelProfile, ranked_models: list[ModelProfile],
                 route: RoutingDecision, use_ensemble: bool) -> ExecutionPlan:
        use_tools = route.requires_tools and target.capabilities.tools >= 0.5
        gen = "coder" if use_tools else "reasoner"
        if use_ensemble and len(ranked_models) > 1:
            ids = [target.id] + [m.id for m in ranked_models if m.id != target.id][:2]
            return ExecutionPlan(strategy="escalated-ensemble", steps=[
                ExecutionStep(worker=gen, models=ids, parallel=True, use_tools=use_tools),
                ExecutionStep(worker="judge", models=[target.id]),
            ])
        return ExecutionPlan(strategy="escalated", steps=[
            ExecutionStep(worker=gen, models=[target.id], use_tools=use_tools),
            ExecutionStep(worker="critic", models=[self._independent(target, ranked_models).id]),
        ])

    def research(self, ranked_models: list[ModelProfile], budget: CognitiveBudget,
                 route: RoutingDecision) -> ExecutionPlan:
        """Research graph: decompose -> answer sub-questions in parallel -> contradictions -> critic."""
        width = max(1, min(3, budget.max_parallel_workers, len(ranked_models)))
        steps = [ExecutionStep(worker="research", models=[m.id for m in ranked_models[:width]],
                               parallel=True, use_tools=True)]
        if budget.max_model_calls >= width + 3:
            steps.append(ExecutionStep(worker="critic",
                                       models=[self._independent(ranked_models[0], ranked_models).id]))
        return ExecutionPlan(strategy="research-graph", steps=steps)

    def execute_and_verify(self, model: ModelProfile, ranked_models: list[ModelProfile]) -> ExecutionPlan:
        """Metacognition asked to run the code before trusting it."""
        tool_model = model if model.capabilities.tools >= 0.5 else next(
            (m for m in ranked_models if m.capabilities.tools >= 0.5), model)
        return ExecutionPlan(strategy="execute-verify", steps=[
            ExecutionStep(worker="coder", models=[tool_model.id], use_tools=True),
            ExecutionStep(worker="critic", models=[self._independent(tool_model, ranked_models).id]),
        ])

    @staticmethod
    def _independent(model: ModelProfile, ranked: list[ModelProfile]) -> ModelProfile:
        """A critic should ideally be a different model (and provider) than the author."""
        for m in ranked:
            if m.id != model.id and m.provider != model.provider:
                return m
        for m in ranked:
            if m.id != model.id:
                return m
        return model

    @staticmethod
    def _cheapest_adequate(route: RoutingDecision, ranked: list[ModelProfile],
                           request: HydraRequest) -> ModelProfile:
        if request.mode in (ExecutionMode.DEEP, ExecutionMode.MAX):
            return ranked[0]
        adequate = [m for m in ranked if m.quality(route.task_type) >= ADEQUATE_QUALITY]
        if not adequate:
            return ranked[0]
        return min(adequate, key=lambda m: (m.tier, m.estimated_latency_ms))
