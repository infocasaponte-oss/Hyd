# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA kernel - the cognitive operating system core.

                    META CONTROLLER
                          │
          ┌───────────────┼───────────────┐
       POLICY           ROUTER          BUDGET
          └───────────────┼───────────────┘
                   COGNITIVE KERNEL
          ┌───────────────┼───────────────┐
        MODELS          TOOLS           MEMORY
          └───────┬───────┴───────┬───────┘
             WORLD STATE       EVIDENCE
                  └───────┬───────┘
                      VERIFIER
                    BELIEF STATE
                  ARTIFACT ENGINE
                       OUTPUT

Four loops run over every task: cognition (policy, cache, router, memory, perception,
planner), execution (workers, models, tools, simulation), verification (verifier,
confidence, uncertainty router, metacognition) and learning (registry, telemetry,
memory, counterfactuals, learned router).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from hydra.analysis.counterfactual import CounterfactualEngine, CounterfactualStats
from hydra.artifacts.engine import ArtifactEngine
from hydra.cache.semantic import SemanticCache
from hydra.core.budget import BudgetExceeded, BudgetTracker, budget_for
from hydra.core.inference_budget import use_inference_budget
from hydra.core.context import TaskContext
from hydra.core.contracts import (
    Claim,
    ExecutionMode,
    HydraMeta,
    HydraRequest,
    HydraResponse,
    ModelRequest,
    RoutingDecision,
    TaskType,
)
from hydra.core.errors import ErrorKind, ModelError, RetryAction, decide
from hydra.core.events import EventType
from hydra.core.state import TaskStatus
from hydra.core.termination import TerminationPolicy
from hydra.memory.compiler import MemoryCompiler, OutcomeRecord
from hydra.memory.compression import compress
from hydra.memory.context import ContextBudget
from hydra.memory.failures import FailureMemory
from hydra.memory.retriever import MemoryRetriever
from hydra.meta.controller import MetaAction, MetacognitiveController
from hydra.policy.kernel import PolicyKernel, Sensitivity
from hydra.provenance.engine import ProvenanceEngine
from hydra.registry.models import ModelProfile
from hydra.registry.registry import ModelRegistry
from hydra.research.graph import ResearchWorker
from hydra.router.learned import ABRouter, LearnedRoutingPolicy
from hydra.router.router import CognitiveRouter
from hydra.router.scoring import score_model
from hydra.scheduler.parallel import run_parallel, speculative
from hydra.scheduler.planner import ExecutionPlan, NoModelAvailable, Planner
from hydra.telemetry.metrics import InferenceRun, TaskRecord, TelemetryStore
from hydra.tools.capabilities import capabilities_for
from hydra.tools.definitions import ToolContext
from hydra.verification.confidence import ConfidenceInputs, confidence_score
from hydra.verification.consensus import agreement, pair_agreement
from hydra.verification.uncertainty import VERIFY_SCHEMA, apply_verdict, assess_claims, segment_claims
from hydra.verification.grounding import coverage as source_coverage
from hydra.verification.grounding import has_source
from hydra.verification.grounding import repair as source_abstention
from hydra.verification.grounding import strip_unsourced_urls
from hydra.verification.verifier import VerificationResult, Verifier
from hydra.workers.coder import CoderWorker
from hydra.workers.critic import CriticWorker
from hydra.workers.judge import JudgeResult, JudgeWorker
from hydra.workers.perception import PerceptionWorker
from hydra.workers.reasoner import ReasonerWorker
from hydra.workers.synthesizer import SynthesisInput, SynthesizerWorker

log = logging.getLogger("hydra.kernel")


class GenerationFailed(RuntimeError):
    def __init__(self, last_error: BaseException) -> None:
        super().__init__(str(last_error))
        self.last_error = last_error


_PUBLIC_FAILURE = {
    "timeout": "the task exceeded its time budget",
    "oom": "the model runtime ran out of memory",
    "invalid_json": "the model did not return valid structured output",
    "tool_unavailable": "a required tool is unavailable",
    "rate_limit": "the model runtime is rate limited",
    "model_refusal": "the model refused the request",
    "hallucinated_tool": "the model requested a tool that does not exist",
    "permission": "the action is not permitted by policy",
    "unavailable": "no model runtime is available",
}


class HydraTaskFailed(RuntimeError):
    """The message may carry internal detail (paths, provider URLs): it is logged and stored in
    the task events, while API clients receive :meth:`public_message` plus the task id."""

    def __init__(self, task_id: UUID, message: str, kind: str = "unknown") -> None:
        super().__init__(message)
        self.task_id = task_id
        self.kind = kind

    def public_message(self) -> str:
        return _PUBLIC_FAILURE.get(self.kind, "the task failed") + f" (task {self.task_id})"


class KernelConfig(BaseModel):
    """Everything HYDRA Lab may vary in an experiment (policies, prompts, routers, models)."""

    model_config = {"extra": "forbid"}

    accept_confidence: float = 0.72
    claim_threshold: float = 0.6
    max_claim_checks: int = 3
    learned_fraction: float = 0.2
    refit_every: int = 50
    prompts: dict[str, str] = Field(default_factory=dict)
    disabled_models: set[str] = Field(default_factory=set)
    enabled_models: set[str] = Field(default_factory=set)
    uncertainty_routing: bool = True
    semantic_cache: bool = True
    compression_keep_last: int = 4
    time_scale: float = 1.0
    world_context: bool = True
    """Add a Graph-RAG context packet from the World Model during RETRIEVING."""
    capture: bool = True
    """Run the capture pipeline (world, artifacts, corpus, ledger, flight recorder) on completion."""
    deterministic_first: bool = False
    """Answer with a deterministic solver (calculator, sympy, JSON validator...) when it is certain."""

    def merged(self, overrides: dict) -> KernelConfig:
        return KernelConfig.model_validate({**self.model_dump(), **overrides})


class HydraKernel:
    def __init__(
        self,
        *,
        router: CognitiveRouter,
        registry: ModelRegistry,
        planner: Planner,
        reasoner: ReasonerWorker,
        coder: CoderWorker,
        critic: CriticWorker,
        judge: JudgeWorker,
        synthesizer: SynthesizerWorker,
        verifier: Verifier,
        bus,
        retriever: MemoryRetriever | None = None,
        memory_compiler: MemoryCompiler | None = None,
        telemetry: TelemetryStore | None = None,
        termination: TerminationPolicy | None = None,
        workspace: Path = Path("workspace"),
        network_domains: list[str] | None = None,
        public_web_enabled: bool = False,
        policy: PolicyKernel | None = None,
        cache: SemanticCache | None = None,
        failures: FailureMemory | None = None,
        learned: LearnedRoutingPolicy | None = None,
        perception: PerceptionWorker | None = None,
        research: ResearchWorker | None = None,
        config: KernelConfig | None = None,
        capture=None,
        world_rag=None,
        policy_dsl=None,
        solvers=None,
        scheduler=None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.planner = planner
        self.reasoner = reasoner
        self.coder = coder
        self.critic = critic
        self.judge = judge
        self.synthesizer = synthesizer
        self.verifier = verifier
        self.bus = bus
        self.retriever = retriever
        self.memory_compiler = memory_compiler
        self.telemetry = telemetry
        self.workspace = workspace
        self.network_domains = network_domains
        self.public_web_enabled = public_web_enabled
        self.policy = policy or PolicyKernel()
        self.cache = cache
        self.failures = failures
        self.learned = learned or LearnedRoutingPolicy()
        self.perception = perception or PerceptionWorker(reasoner.invoker)
        self.research = research or ResearchWorker(reasoner.invoker, coder)
        self.config = config or KernelConfig()
        self.capture = capture
        self.world_rag = world_rag
        self.policy_dsl = policy_dsl
        self.solvers = solvers
        self.scheduler = scheduler
        self.ab = ABRouter(self.learned, self.config.learned_fraction)
        self.meta = MetacognitiveController(termination, self.config.accept_confidence, self.config.claim_threshold)
        self.provenance = ProvenanceEngine()
        self.artifacts = ArtifactEngine()
        self.counterfactual = CounterfactualEngine(registry)
        self.counterfactual_stats = CounterfactualStats()
        self._tasks_since_refit = 0

    def apply_config(self, config: KernelConfig) -> None:
        """Change the production configuration in place (HYDRA Lab promotion)."""
        self.config = config
        self.ab = ABRouter(self.learned, config.learned_fraction)
        self.meta = MetacognitiveController(self.meta.termination, config.accept_confidence, config.claim_threshold)

    def with_config(self, **overrides) -> HydraKernel:
        """A sibling kernel sharing every component but with a different configuration (HYDRA Lab)."""
        clone = object.__new__(HydraKernel)
        clone.__dict__.update(self.__dict__)
        clone.config = self.config.merged(overrides)
        clone.ab = ABRouter(self.learned, clone.config.learned_fraction)
        clone.meta = MetacognitiveController(self.meta.termination, clone.config.accept_confidence,
                                             clone.config.claim_threshold)
        return clone

    # =====================================================================================
    async def run(self, request: HydraRequest, task_id: UUID | None = None, *,
                  shadow: bool = False, learn: bool = True) -> HydraResponse:
        budget = BudgetTracker(budget_for(request, self.config.time_scale))
        # Native executors reached from this task reserve from the same model-call counter.
        with use_inference_budget(budget.calls):
            return await self._run(request, task_id, shadow=shadow, learn=learn, budget=budget)

    async def _run(self, request: HydraRequest, task_id: UUID | None, *,
                   shadow: bool, learn: bool, budget: BudgetTracker) -> HydraResponse:
        ctx = TaskContext(request=request, bus=self.bus, budget=budget)
        if task_id is not None:
            ctx.task_id = task_id
        ctx.shadow, ctx.learn, ctx.prompts = shadow, learn and not shadow, dict(self.config.prompts)
        started = time.perf_counter()
        best: tuple[float, dict, JudgeResult | None, VerificationResult] | None = None
        claims: list[Claim] = []
        best_claims: list[Claim] = []
        plan: ExecutionPlan | None = None
        arm = "heuristic"

        # ---------------- policy kernel (before anything is logged or sent anywhere) ----------------
        rp = self.policy.check_request(request)
        ctx.sensitivity = int(rp.sensitivity)
        objective = request.last_user_text[:4000]
        if rp.sensitivity >= Sensitivity.CONFIDENTIAL:
            objective = self.policy.redact(objective)
        await ctx.emit(EventType.TASK_CREATED, "kernel", {
            "objective": objective, "mode": request.mode.value, "private": request.private,
            "budget": ctx.budget.budget.model_dump(), "shadow": shadow,
        })
        await ctx.emit(EventType.POLICY_EVALUATED, "policy_kernel", {
            "allowed": rp.allowed, "reason": rp.reason, "sensitivity": rp.sensitivity.name.lower(),
            "local_only": rp.local_only, "findings": rp.findings,
        })
        if not rp.allowed:
            return await self._early(ctx, started, "refuse",
                                     f"No puedo ayudar con esta petición: {rp.reason}.")
        if rp.local_only and not request.local_only:
            request = request.model_copy(update={"local_only": True})
            ctx.request = request

        try:
            # Engine ownership is configured metadata, not a model-generated fact.
            from hydra.core.identity import creator_answer
            creators = {m.engine_creator for m in self.registry.all() if m.enabled and m.engine_creator}
            identity = creator_answer(request.last_user_text, next(iter(creators)) if len(creators) == 1 else "")
            if identity and not request.images:
                return await self._early(ctx, started, "answer", identity)
            # ---------------- semantic cache ----------------
            if self.cache is not None and self.config.semantic_cache and not shadow:
                hit = await self.cache.lookup(request)
                if hit is not None:
                    return await self._cache_hit(ctx, hit, started)

            # ---------------- deterministic-first (capability market) ----------------
            if self.config.deterministic_first and self.solvers is not None and not request.images:
                solved = self.solvers.solve(request.last_user_text)
                if solved is not None:
                    return await self._solved(ctx, started, solved)

            # ---------------- cognition loop ----------------
            await ctx.status(TaskStatus.ROUTING)
            route = await self.router.route(request)
            ctx.route = route
            arm = self.ab.arm_for(ctx.task_id)
            await ctx.emit(EventType.ROUTE_SELECTED, "router", {**route.model_dump(mode="json"), "arm": arm})

            first = self.meta.before(request, route)
            await ctx.emit(EventType.META_DECISION, "meta", first.model_dump())
            if first.action == MetaAction.ASK:
                return await self._early(ctx, started, "ask", first.question or "¿Puedes darme más detalles?")

            ctx.tool_ctx = ToolContext(
                task_id=ctx.task_id,
                private=request.private,
                allow_high_risk_tools=request.allow_high_risk_tools,
                capabilities=capabilities_for(route, self.network_domains),
                workspace=self.workspace,
                approved=set(request.approved_actions),
                shadow=shadow,
            )
            if not self.public_web_enabled:
                ctx.tool_ctx.capabilities.tools -= {"web.search", "web.read"}
                ctx.tool_ctx.capabilities.public_web = False
            from hydra.tools.web_context import requested_web, web_query
            search_query = web_query(request.messages)
            explicit_web = self.public_web_enabled and requested_web(search_query)
            if explicit_web and not request.private and not shadow:
                # An explicit user request to consult the web does not depend
                # on a classifier confusing a technical question with coding.
                ctx.tool_ctx.capabilities.tools |= {"web.search", "web.read"}
                ctx.tool_ctx.capabilities.public_web = True
            ctx.world.from_text(request.text)
            await ctx.status(TaskStatus.RETRIEVING)
            await self._retrieve_memory(ctx)
            await self._world_context(ctx)
            if self.public_web_enabled and (route.task_type == TaskType.RESEARCH or explicit_web) and not request.private and not shadow:
                from hydra.tools.web_context import collect_web_context, render_web_context, fetched_sources
                evidence, _ = await collect_web_context(ctx, self.coder.executor, search_query)
                if evidence:
                    ctx.web_context = [render_web_context(evidence)]
                    ctx.web_sources = fetched_sources(evidence)
                    if not ctx.web_sources:
                        ctx.degradations.append("No se leyó ninguna fuente web; los enlaces de búsqueda no verifican la respuesta.")

            await ctx.status(TaskStatus.PLANNING)
            ctx.ranked = self._rank(ctx, route)
            if not ctx.ranked and await self._fit_oversized(ctx):
                request = ctx.request
                ctx.ranked = self._rank(ctx, route)
            if not ctx.ranked:
                raise NoModelAvailable("no model satisfies the policy and constraints of this request")
            ctx.ranked = self.ab.apply(arm, ctx.ranked, route, request)
            await ctx.emit(EventType.MODELS_RANKED, "registry", {"arm": arm, "ranked": [
                {"model": m.id, "score": round(score_model(m, route, request), 4)} for m in ctx.ranked
            ]})
            await self._compress_context(ctx)
            if request.images:
                await self._perceive(ctx, route)
            if not ctx.world.empty:
                await ctx.emit(EventType.WORLD_UPDATED, "world", {"world": ctx.world.model_dump(mode="json")})

            if first.action == MetaAction.SEARCH:
                plan = self.planner.research(ctx.ranked, ctx.budget.budget, route)
            else:
                plan = self.planner.create(route, ctx.ranked, ctx.budget.budget, request,
                                           tools_available=bool(ctx.tool_ctx.capabilities.tools))
            await ctx.emit(EventType.PLAN_CREATED, "planner", plan.model_dump())
            await ctx.status(TaskStatus.EXECUTING)

            # ---------------- execution + verification loops ----------------
            while True:
                ctx.budget.steps += 1
                try:
                    chosen, judged = await self._execute_plan(ctx, plan)
                except (GenerationFailed, BudgetExceeded) as exc:
                    # a later attempt (escalation) failed or ran out of budget: keep the best verified answer
                    if best is not None:
                        await ctx.emit(EventType.RETRY_DECIDED, "kernel", {
                            "action": "keep_previous_best", "error": str(exc)[:300]})
                        await ctx.status(TaskStatus.VERIFYING)
                        break
                    if isinstance(exc, BudgetExceeded):
                        raise
                    plan = await self._recover(ctx, plan, exc)
                    continue

                await ctx.status(TaskStatus.VERIFYING)
                verification, confidence = await self._verify(ctx, chosen, judged)
                claims = await self._assess_claims(ctx, chosen, confidence, verification)
                claims_checked = False

                while True:
                    uncertain = sum(1 for c in claims if c.status in ("uncertain", "refuted"))
                    decision = self.meta.after_verification(
                        confidence=confidence, verified=verification.verified, passed=verification.passed,
                        route=route, budget=ctx.budget, tools_used=bool(ctx.state.tools_used),
                        tools_available=bool(ctx.tool_ctx.capabilities.tools),
                        uncertain_claims=uncertain if self.config.uncertainty_routing else 0,
                        claims_checked=claims_checked, can_escalate=ctx.budget.can_escalate(),
                    )
                    await ctx.emit(EventType.META_DECISION, "meta", decision.model_dump(mode="json"))
                    if decision.action != MetaAction.VERIFY_CLAIMS:
                        break
                    claims, confidence = await self._investigate_claims(ctx, chosen, claims, confidence)
                    claims_checked = True

                if best is None or confidence > best[0]:
                    best = (confidence, chosen, judged, verification)
                    best_claims = claims

                next_plan = None
                if decision.action == MetaAction.EXECUTE:
                    current = self.registry.models.get(chosen.get("model", "")) or ctx.ranked[0]
                    next_plan = self.planner.execute_and_verify(current, ctx.ranked)
                elif decision.action == MetaAction.ESCALATE:
                    if (esc := self._escalation(ctx, chosen, plan)) is not None:
                        target, ensemble = esc
                        next_plan = self.planner.escalate(target, ctx.ranked, route, ensemble)
                if next_plan is None:
                    break

                await ctx.status(TaskStatus.ESCALATING)
                ctx.budget.escalations += 1
                await ctx.emit(EventType.ESCALATED, "kernel", {
                    "from": chosen.get("model"), "action": decision.action.value, "strategy": next_plan.strategy,
                    "confidence": confidence, "verified": verification.passed,
                })
                plan = next_plan
                await ctx.status(TaskStatus.PLANNING)
                await ctx.emit(EventType.PLAN_REVISED, "planner", plan.model_dump())
                await ctx.status(TaskStatus.EXECUTING)

            confidence, chosen, judged, verification = best
            claims = best_claims
            await ctx.status(TaskStatus.SYNTHESIZING)
            answer = await self._synthesize(ctx, chosen, judged, verification, claims)
            await ctx.emit(EventType.SYNTHESIS_COMPLETED, "synthesizer", {"answer": answer})
            answer, verification, confidence = await self._enforce_source_coverage(
                ctx, answer, verification, confidence)
            if has_source(request.last_user_text) and not chosen.get("research"):
                # Only the source in the latest message: earlier turns may hold invented links.
                answer, invented = strip_unsourced_urls(answer, request.last_user_text)
                if invented:
                    ctx.degradations.append("Se retiraron enlaces que no aparecen en la fuente aportada: "
                                            + ", ".join(invented))

            records = self.provenance.build(claims, ctx.state, chosen, verification.verified,
                                            documents={"request": request.text})
            await ctx.emit(EventType.PROVENANCE_RECORDED, "provenance",
                           {"records": [r.model_dump(mode="json") for r in records]})
            artifacts = self.artifacts.extract(
                answer, plan=plan.model_dump() if plan else None, research_graph=ctx.state.research_graph,
                images=request.images, claims=[c.model_dump() for c in claims], task_type=route.task_type.value)
            learning: dict = {}
            if self.capture is not None and self.config.capture and ctx.learn and not shadow:
                await ctx.status(TaskStatus.CAPTURING)
                try:
                    learning = await self.capture.capture(
                        ctx, answer=answer, artifacts=artifacts, claims=claims,
                        provenance=[r.model_dump(mode="json") for r in records], confidence=confidence,
                        verified=verification.verified)
                except Exception:
                    log.exception("capture pipeline failed")
            for a in artifacts:
                await ctx.emit(EventType.ARTIFACT_CREATED, "artifact_engine", a.model_dump(mode="json"))
            await ctx.status(TaskStatus.COMPLETED)

            uncertainties = list(ctx.degradations) + list(verification.uncertainties)
            if not verification.passed:
                uncertainties.insert(0, "La respuesta no superó la verificación: trátala con cautela.")
            uncertainties += [f"Afirmación dudosa: {c.text[:200]}" + (f" → {c.correction}" if c.correction else "")
                              for c in claims if c.status == "refuted"]
            if ctx.web_sources:
                from hydra.tools.web_context import attach_sources
                answer = attach_sources(answer, ctx.web_sources)
            response = HydraResponse(
                answer=answer,
                meta=HydraMeta(
                    task_id=str(ctx.task_id),
                    status=TaskStatus.COMPLETED.value,
                    task_type=route.task_type,
                    mode=request.mode,
                    models_used=ctx.state.models_used,
                    tools_used=ctx.state.tools_used,
                    verified=verification.verified,
                    confidence=confidence,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    escalations=ctx.budget.escalations,
                    steps=ctx.budget.steps,
                    sensitivity=rp.sensitivity.name.lower(),
                ),
                uncertainties=uncertainties,
                claims=claims,
                artifacts=[a.model_dump(mode="json") for a in artifacts],
                pending_confirmations=ctx.state.pending_confirmations,
                learning=learning,
            )
            await ctx.emit(EventType.TASK_COMPLETED, "kernel", {
                "confidence": confidence, "verified": verification.verified, "budget": ctx.budget.snapshot(),
            })
        except Exception as exc:
            kind, _ = decide(exc)
            if not ctx.machine.terminal:
                await ctx.status(TaskStatus.FAILED)
            await ctx.emit(EventType.TASK_FAILED, "kernel", {"error": str(exc)[:1000], "kind": kind.value,
                                                             "budget": ctx.budget.snapshot()})
            if self.capture is not None and self.config.capture and ctx.learn and not shadow:
                await self.capture.capture_failure(ctx, str(exc))
            await self._learn(ctx, None, None, None, None, arm)
            raise HydraTaskFailed(ctx.task_id, str(exc), kind.value) from exc

        # ---------------- learning loop ----------------
        await self._learn(ctx, chosen, verification, confidence, response, arm)
        return response

    # =====================================================================================
    async def _early(self, ctx: TaskContext, started: float, decision: str, answer: str) -> HydraResponse:
        """Finish without models: policy refusal or a clarifying question."""
        await ctx.status(TaskStatus.COMPLETED)
        response = HydraResponse(
            answer=answer,
            meta=HydraMeta(task_id=str(ctx.task_id), status=TaskStatus.COMPLETED.value,
                           task_type=ctx.route.task_type if ctx.route else TaskType.CHAT,
                           mode=ctx.request.mode, models_used=[], tools_used=[], verified=False,
                           confidence=1.0 if decision == "refuse" else 0.0,
                           latency_ms=round((time.perf_counter() - started) * 1000, 2),
                           sensitivity=Sensitivity(ctx.sensitivity).name.lower(), decision=decision),
        )
        await ctx.emit(EventType.SYNTHESIS_COMPLETED, "kernel", {"answer": answer, "decision": decision})
        await ctx.emit(EventType.TASK_COMPLETED, "kernel", {"decision": decision, "budget": ctx.budget.snapshot()})
        await self._save_task(ctx, response)
        return response

    async def _solved(self, ctx: TaskContext, started: float, solved) -> HydraResponse:
        """Deterministic solver answered with certainty: no model call (capability market)."""
        await ctx.emit(EventType.TOOL_COMPLETED, "capability_market", {
            "tool": f"solver:{solved.solver}", "arguments": {"input": solved.input}, "result": solved.output,
            "success": True, "duration_ms": solved.duration_ms, "requested_by": "kernel"})
        await ctx.status(TaskStatus.COMPLETED)
        response = HydraResponse(
            answer=solved.answer,
            meta=HydraMeta(task_id=str(ctx.task_id), status=TaskStatus.COMPLETED.value, task_type=TaskType.REASONING,
                           mode=ctx.request.mode, models_used=[], tools_used=[f"solver:{solved.solver}"],
                           verified=True, confidence=solved.confidence,
                           latency_ms=round((time.perf_counter() - started) * 1000, 2),
                           sensitivity=Sensitivity(ctx.sensitivity).name.lower(), decision="answer"),
        )
        await ctx.emit(EventType.SYNTHESIS_COMPLETED, "capability_market", {"answer": solved.answer})
        await ctx.emit(EventType.TASK_COMPLETED, "kernel", {"deterministic": solved.solver,
                                                           "confidence": solved.confidence})
        await self._save_task(ctx, response)
        return response

    async def _fit_oversized(self, ctx: TaskContext) -> bool:
        """Graceful degradation: a message larger than every model's window is cut (head + tail)
        to fit the largest eligible window instead of failing the task."""
        avail = [m for m in self.registry.available() if m.local or not ctx.request.private]
        if not avail:
            return False
        window = max(m.context_window for m in avail)
        budget = int(window * 0.55 * 4)
        text = ctx.request.last_user_text
        if len(text) <= budget:
            return False
        head, tail = int(budget * 0.7), int(budget * 0.3)
        cut = (text[:head] + f"\n\n[... HYDRA omitió {len(text) - head - tail} caracteres: el contexto supera "
               f"la ventana de todos los modelos disponibles ...]\n\n" + text[-tail:])
        msgs = list(ctx.request.messages)
        idx = max(i for i, m in enumerate(msgs) if m.role == "user") if any(m.role == "user" for m in msgs) \
            else len(msgs) - 1
        msgs[idx] = msgs[idx].model_copy(update={"content": cut})
        ctx.request = ctx.request.model_copy(update={"messages": msgs})
        ctx.conversation = None
        note = (f"El mensaje ({len(text)} caracteres) superaba la ventana de contexto de todos los modelos "
                f"({window} tokens): se analizó un extracto (inicio y final).")
        ctx.degradations.append(note)
        await ctx.emit(EventType.CONTEXT_COMPRESSED, "kernel", {"truncated_from": len(text), "to": len(cut),
                                                                "window": window, "strategy": "head+tail"})
        return True

    async def _world_context(self, ctx: TaskContext) -> None:
        """Graph RAG over the persistent World Model (rights-aware: visibility follows sensitivity/locality)."""
        if self.world_rag is None or not self.config.world_context:
            return
        from hydra.world.model import Visibility

        private = ctx.request.private or ctx.sensitivity >= Sensitivity.CONFIDENTIAL
        vis = Visibility.CONFIDENTIAL if private else Visibility.INTERNAL
        try:
            packet = self.world_rag.packet(ctx.request.last_user_text[:2000], max_visibility=vis, limit=8)
        except Exception:
            log.exception("world context failed")
            return
        if packet.verified_facts or packet.contested_beliefs:
            lines = [f"[world] {f}" for f in packet.verified_facts]
            lines += [f"[world:contested] {c}" for c in packet.contested_beliefs]
            ctx.memory_lines = [*ctx.memory_lines, *lines]
            await ctx.emit(EventType.WORLD_UPDATED, "world_model", {"packet": packet.model_dump(mode="json")})

    async def _cache_hit(self, ctx: TaskContext, hit, started: float) -> HydraResponse:
        cached, score = hit
        cached.meta.task_id = str(ctx.task_id)
        cached.meta.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        await ctx.emit(EventType.CACHE_HIT, "semantic_cache", {"similarity": round(score, 4)})
        await ctx.status(TaskStatus.COMPLETED)
        await ctx.emit(EventType.SYNTHESIS_COMPLETED, "semantic_cache", {"answer": cached.answer})
        await ctx.emit(EventType.TASK_COMPLETED, "kernel", {"cached": True, "confidence": cached.meta.confidence})
        await self._save_task(ctx, cached)
        return cached

    def _rank(self, ctx: TaskContext, route: RoutingDecision) -> list[ModelProfile]:
        request = ctx.request
        reasoning_route = route.model_copy(update={"requires_vision": False}) if request.images else route
        ranked = self.registry.select(request, reasoning_route)
        if self.config.enabled_models:
            # Lab canary of a new model: the candidate goes first even if not yet enabled in production.
            present = {m.id for m in ranked}
            extra = [m for m in self.registry.all() if m.id in self.config.enabled_models
                     and m.id not in present and (m.local or not request.private)]
            ranked = extra + ranked
        ranked = [m for m in ranked if m.id not in self.config.disabled_models
                  and self.policy.model_allowed(m.id, m.local, Sensitivity(ctx.sensitivity))]
        if self.policy_dsl is not None:
            cls = Sensitivity(ctx.sensitivity).name
            ranked = [m for m in ranked if self.policy_dsl.evaluate({
                "classification": "TRADE_SECRET" if cls == "SECRET" else cls, "model": m.id,
                "target_runtime": "LOCAL" if m.local else "CLOUD", "mode": request.mode.value,
                "tenant": request.metadata.get("tenant_id")}).effect != "deny"]
        if self.failures is not None:
            cond = {"ctx_bucket": next((b for b in (4_000, 16_000, 32_000, 80_000)
                                        if len(request.text) // 4 <= b), 1_000_000)}
            safe = [m for m in ranked if not self.failures.should_avoid(m.id, cond)]
            ranked = safe or ranked  # never leave the task without a model
        if self.scheduler is not None and len(ranked) > 1:
            try:
                ranked = self.scheduler.rerank(
                    ranked, quality_of=lambda m: m.quality(route.task_type), mode=request.mode.value,
                    private=request.private, conversation=request.metadata.get("conversation_id"))
            except Exception:
                log.exception("cluster rerank failed")
        return ranked

    async def _retrieve_memory(self, ctx: TaskContext) -> None:
        if self.retriever is None or (ctx.request.mode == ExecutionMode.FAST and not ctx.route.requires_memory):
            return
        try:
            ranked = await self.retriever.retrieve(ctx.request.last_user_text, ctx.route.task_type.value)
        except Exception:
            log.exception("memory retrieval failed")
            return
        if not ranked:
            return
        ctx.memory_lines = [f"[{i.status.value}] {i.text}" for i, _ in ranked]
        ctx.memory_ids = [i.id for i, _ in ranked]
        top = [s for _, s in ranked[:3]]
        ctx.knowledge_coverage = round(sum(top) / len(top), 4)
        items = [{"id": i.id, "type": i.memory_type.value, "text": i.text, "status": i.status.value,
                  "score": round(s, 4)} for i, s in ranked]
        ctx.world.from_memory(items)
        await ctx.emit(EventType.MEMORY_RETRIEVED, "retriever", {"items": items})

    async def _compress_context(self, ctx: TaskContext) -> None:
        window = min(m.context_window for m in ctx.ranked[:3])
        budget = ContextBudget.for_window(window).user_tokens
        state, recent = compress(ctx.messages_for_workers(), self.config.compression_keep_last, budget)
        if state is not None:
            ctx.conversation = recent
            ctx.compressed_block = state.render()
            await ctx.emit(EventType.CONTEXT_COMPRESSED, "context_compiler", state.model_dump())

    async def _perceive(self, ctx: TaskContext, route: RoutingDecision) -> None:
        """Perception layer: a VLM turns images into world state for any reasoner."""
        vision_route = route.model_copy(update={"requires_vision": True, "requires_tools": False})
        vlms = [m for m in self.registry.select(ctx.request, vision_route)
                if m.id not in self.config.disabled_models
                and self.policy.model_allowed(m.id, m.local, Sensitivity(ctx.sensitivity))]
        if not vlms:
            ctx.state.uncertainties.append("no vision model available: images were not analysed")
            return
        try:
            obs = await self.perception.execute(ctx, vlms[0])
        except Exception as exc:
            log.warning("perception failed: %s", exc)
            return
        ctx.world.from_perception(obs, source=f"vision:{obs.get('model', vlms[0].id)}")
        if desc := obs.get("description"):
            ctx.memory_lines = [f"[perception] {desc}", *ctx.memory_lines]

    async def _execute_plan(self, ctx: TaskContext, plan: ExecutionPlan) -> tuple[dict, JudgeResult | None]:
        candidates: list[dict] = []
        judged: JudgeResult | None = None
        chosen: dict | None = None

        for step in plan.steps:
            models = [self.registry.models[m] for m in step.models if m in self.registry.models]
            if step.worker == "research" and models:
                try:
                    graph, answers = await self.research.execute(ctx, models[0], models)
                except BudgetExceeded:
                    raise
                except Exception as exc:
                    raise GenerationFailed(exc) from exc
                if not answers:
                    raise GenerationFailed(ModelError("research produced no answers", ErrorKind.MODEL_REFUSAL))
                chosen = {"claim_id": "research:0", "model": models[0].id, "worker": "research", "research": True,
                          "answer": ResearchWorker.merge(ctx.request.last_user_text, graph, answers)}
                await ctx.emit(EventType.ANSWER_PROPOSED, "research", chosen)
                candidates = [chosen]

            elif step.worker in ("reasoner", "coder"):
                worker = self.coder if step.worker == "coder" and step.use_tools else self.reasoner
                calls = [lambda m=m, i=i: worker.execute(ctx, m, index=i) for i, m in enumerate(models)]
                if step.speculative and len(calls) > 2:
                    finished: list[dict] = []

                    def early_consensus(c: dict) -> bool:
                        agree = any(pair_agreement(c["answer"], f["answer"]) >= 0.8 for f in finished)
                        finished.append(c)
                        return agree

                    _, results = await speculative(calls, early_consensus)
                elif step.parallel:
                    results = await run_parallel(calls)
                else:
                    results = await run_parallel(calls[:1])
                new = [r for r in results if isinstance(r, dict) and r.get("answer", "").strip()]
                errors = [r for r in results if isinstance(r, BaseException)]
                if not new:
                    if any(isinstance(e, BudgetExceeded) for e in errors):
                        raise next(e for e in errors if isinstance(e, BudgetExceeded))
                    raise GenerationFailed(errors[-1] if errors else ModelError("empty answer", ErrorKind.MODEL_REFUSAL))
                candidates.extend(new)
                chosen = candidates[0]

            elif step.worker == "judge" and len(candidates) > 1 and models:
                judged = await self.judge.execute(ctx, models[0], candidates)
                chosen = candidates[judged.best_index]
                if judged.merged_answer:
                    chosen = {**chosen, "answer": judged.merged_answer, "merged": True}

            elif step.worker == "critic" and chosen is not None and models and ctx.budget.can_call_model():
                try:
                    await self.critic.execute(ctx, models[0], chosen)
                except BudgetExceeded:
                    pass
                except Exception as exc:  # a failed critic lowers confidence, never the task
                    log.warning("critic failed: %s", exc)

        if chosen is None:
            raise GenerationFailed(ModelError("plan produced no candidate"))
        if judged is None and len(candidates) > 1:
            judged = JudgeWorker.consensus(candidates)
            chosen = candidates[judged.best_index]
        return chosen, judged

    async def _recover(self, ctx: TaskContext, plan: ExecutionPlan, exc: GenerationFailed) -> ExecutionPlan:
        kind, action = decide(exc.last_error)
        if isinstance(exc.last_error, BudgetExceeded) or action == RetryAction.FAIL:
            raise exc.last_error
        await ctx.status(TaskStatus.RETRYING)
        ctx.ranked = [m for m in self._rank(ctx, ctx.route) if m.id not in ctx.failed_models]
        if not ctx.ranked or not ctx.budget.can_call_model() or ctx.budget.max_steps_reached:
            raise exc.last_error
        new_plan = self.planner.replan(plan, action, ctx.route, ctx.ranked, ctx.budget.budget, ctx.request)
        await ctx.emit(EventType.RETRY_DECIDED, "kernel", {"error_kind": kind.value, "action": action.value,
                                                           "scope": "plan"})
        await ctx.emit(EventType.PLAN_REVISED, "planner", new_plan.model_dump())
        await ctx.status(TaskStatus.EXECUTING)
        return new_plan

    async def _verify(self, ctx: TaskContext, chosen: dict, judged: JudgeResult | None
                      ) -> tuple[VerificationResult, float]:
        claim = chosen.get("claim_id", "")
        research = chosen.get("research", False)
        if not research:
            others = [c for c in ctx.state.candidates if c.get("claim_id") != claim]
            for other in others[-4:]:
                a = pair_agreement(chosen["answer"], other.get("answer", ""))
                await self.reasoner.add_evidence(ctx, claim, "model", other.get("model", "?"),
                                                 a if a >= 0.5 else 1 - a, a >= 0.5)

        verification = self.verifier.verify(ctx.request, ctx.route, ctx.state, chosen["answer"],
                                            claim_id=claim, model_id=None if research else chosen.get("model"))
        model = self.registry.models.get(chosen.get("model", ""))
        if research:
            agree = ResearchWorker.consistency([c for c in ctx.state.candidates if c.get("claim_id") != claim])
            if ctx.state.research_graph and any(n["kind"] == "contradiction"
                                                for n in ctx.state.research_graph.get("nodes", [])):
                agree = min(agree or 0.5, 0.4)
        else:
            agree = judged.agreement if judged else agreement([c["answer"] for c in ctx.state.candidates])
        confidence = confidence_score(ConfidenceInputs(
            agreement=agree,
            verification=verification.confidence_signal,
            evidence=verification.evidence,
            tool_validation=verification.tool_validation,
            historical_accuracy=model.quality(ctx.route.task_type) if model else None,
            knowledge_coverage=ctx.knowledge_coverage,
        ))
        if not verification.passed:
            confidence = min(confidence, 0.5)

        await ctx.emit(EventType.BELIEF_UPDATED, "verifier", {
            "id": "belief:answer",
            "statement": chosen["answer"][:1000],
            "confidence": confidence,
            "evidence_ids": [e.id for e in ctx.state.evidence.values() if e.claim_id == claim],
            "contradictions": judged.disagreements if judged else [],
        })
        await ctx.emit(EventType.VERIFICATION_COMPLETED, "verifier",
                       {**verification.model_dump(), "confidence": confidence, "target": claim})
        return verification, confidence

    async def _enforce_source_coverage(self, ctx: TaskContext, answer: str, verification: VerificationResult,
                                       confidence: float) -> tuple[str, VerificationResult, float]:
        """A question about an article/code name absent from the supplied source gets a grounded
        abstention instead of content the model cannot have read (whatever model answered)."""
        failed = next((c for c in verification.checks
                       if c.name == "source_coverage" and not c.passed), None)
        if failed is None:
            return answer, verification, confidence
        cov = source_coverage(ctx.request)
        if cov is None or not cov.missing:
            return answer, verification, confidence
        repaired = source_abstention(cov)
        checked = self.verifier.verify(ctx.request, ctx.route, ctx.state, repaired)
        ctx.degradations.append("La respuesta del modelo describía contenido ausente de la fuente "
                                f"({failed.detail}); se sustituyó por una abstención fundamentada.")
        await ctx.emit(EventType.VERIFICATION_COMPLETED, "verifier", {
            **checked.model_dump(), "confidence": checked.confidence_signal, "target": "source_coverage_repair",
            "replaced_answer": answer[:1000],
        })
        return repaired, checked, checked.confidence_signal

    async def _assess_claims(self, ctx: TaskContext, chosen: dict, confidence: float,
                             verification: VerificationResult) -> list[Claim]:
        claims = segment_claims(chosen["answer"])
        others = [c.get("answer", "") for c in ctx.state.candidates
                  if c.get("claim_id") != chosen.get("claim_id") and not chosen.get("research")]
        tool_outputs = [str(r.get("result", "")) for r in ctx.state.tool_results]
        issues = [i for c in ctx.state.critiques for i in c.get("issues", [])]
        claims = assess_claims(claims, confidence, others, tool_outputs, issues, self.config.claim_threshold)
        await ctx.emit(EventType.CLAIMS_ASSESSED, "uncertainty_router",
                       {"claims": [c.model_dump() for c in claims], "stage": "assessed"})
        return claims

    async def _investigate_claims(self, ctx: TaskContext, chosen: dict, claims: list[Claim],
                                  confidence: float) -> tuple[list[Claim], float]:
        """Investigate ONLY the uncertain claims with an independent model."""
        current = self.registry.models.get(chosen.get("model", "")) or ctx.ranked[0]
        checker = self.planner._independent(current, ctx.ranked)
        targets = sorted((c for c in claims if c.status == "uncertain"), key=lambda c: c.confidence)
        for c in targets[: self.config.max_claim_checks]:
            if not ctx.budget.can_call_model():
                break
            try:
                resp = await self.reasoner.invoker.invoke(ctx, checker, ModelRequest(messages=[
                    {"role": "system", "content": "You verify ONE claim. Return ONLY JSON: "
                                                  '{"verdict": "supported|refuted|uncertain", '
                                                  '"correction": string|null, "reason": string}.'},
                    {"role": "user", "content": f"TASK:\n{ctx.request.last_user_text[:3000]}\n\nCLAIM:\n{c.text}"},
                ], temperature=0, max_tokens=400, response_schema=VERIFY_SCHEMA), role="claim_verifier", hedge=False)
                apply_verdict(c, resp.structured or {})
            except BudgetExceeded:
                break
            except Exception as exc:
                log.warning("claim verification failed: %s", exc)
        refuted = [c for c in claims if c.status == "refuted"]
        if refuted:
            confidence = min(confidence, 0.55)
        elif claims and all(c.status == "supported" for c in claims):
            confidence = max(confidence, sum(c.confidence for c in claims) / len(claims))
        await ctx.emit(EventType.CLAIMS_ASSESSED, "uncertainty_router",
                       {"claims": [c.model_dump() for c in claims], "stage": "investigated",
                        "checker": checker.id})
        return claims, round(confidence, 4)

    def _escalation(self, ctx: TaskContext, chosen: dict, plan: ExecutionPlan
                    ) -> tuple[ModelProfile, bool] | None:
        """Smart escalation: 3B -> 8B -> 32B -> large reasoner -> ensemble."""
        if not ctx.budget.can_escalate():
            return None
        current = self.registry.models.get(chosen.get("model", ""))
        ranked = [m for m in ctx.ranked if m.id not in ctx.failed_models]
        if current is not None:
            stronger = [m for m in ranked if m.tier > current.tier]
            if stronger:
                return min(stronger, key=lambda m: (m.tier, -score_model(m, ctx.route, ctx.request))), False
        already_ensemble = "ensemble" in plan.strategy
        if not already_ensemble and len(ranked) >= 2 and ctx.budget.can_call_model(3):
            return ranked[0], True
        return None

    async def _synthesize(self, ctx: TaskContext, chosen: dict, judged: JudgeResult | None,
                          verification: VerificationResult, claims: list[Claim]) -> str:
        artifacts = []
        for r in ctx.state.tool_results[-3:]:
            res = r.get("result")
            if isinstance(res, dict) and "stdout" in res:
                artifacts.append(f"{r['tool']} stdout:\n{str(res['stdout'])[:2000]}")
        refuted = [c for c in claims if c.status == "refuted"]
        inp = SynthesisInput(
            objective=ctx.request.last_user_text[:4000],
            verified_facts=[f["fact"] for f in ctx.state.facts][:20],
            conclusions=[chosen["answer"]],
            uncertainties=(verification.uncertainties[:10]
                           + [f"refuted: {c.text[:200]} -> {c.correction or 'unknown'}" for c in refuted]),
            artifacts=artifacts,
        )
        use_model = (
            (ctx.request.mode in (ExecutionMode.DEEP, ExecutionMode.MAX) and len(ctx.state.candidates) > 1
             and not chosen.get("merged"))
            or bool(refuted)
            or bool(chosen.get("research"))
        )
        model = self.registry.models.get(chosen.get("model", "")) or (ctx.ranked[0] if ctx.ranked else None)
        try:
            return await self.synthesizer.execute(ctx, model, inp, use_model)
        except Exception as exc:
            log.warning("synthesizer failed, returning best candidate: %s", exc)
            return chosen["answer"]

    async def _save_task(self, ctx: TaskContext, response: HydraResponse | None) -> None:
        if self.telemetry is None or ctx.shadow:
            return
        request = ctx.request
        if ctx.sensitivity >= Sensitivity.CONFIDENTIAL:
            request = request.model_copy(update={"messages": [
                m.model_copy(update={"content": self.policy.redact(m.content)}) for m in request.messages]})
        try:
            await self.telemetry.save_task(TaskRecord(
                id=ctx.task_id, status=ctx.machine.status.value,
                request=request.model_dump(mode="json"),
                route=ctx.route.model_dump(mode="json") if ctx.route else None,
                final_response=response.model_dump(mode="json") if response else None,
            ))
        except Exception:
            log.exception("telemetry failed")

    async def _learn(self, ctx: TaskContext, chosen: dict | None, verification: VerificationResult | None,
                     confidence: float | None, response: HydraResponse | None, arm: str) -> None:
        # Counterfactual analysis runs for every completed task (shadow runs included: it is cheap).
        if chosen is not None and response is not None:
            report = self.counterfactual.analyze(ctx.events, chosen, response.answer, self.config.accept_confidence)
            await ctx.emit(EventType.COUNTERFACTUAL_ANALYZED, "counterfactual", report.model_dump())
            if ctx.learn:
                self.counterfactual_stats.add(report)
        if not ctx.learn:
            return

        task_type = ctx.route.task_type if ctx.route else None
        runs: list[InferenceRun] = []
        for e in ctx.events:
            if e.type not in (EventType.MODEL_COMPLETED, EventType.MODEL_FAILED):
                continue
            ok = e.type == EventType.MODEL_COMPLETED
            p = e.payload
            is_chosen = chosen is not None and p.get("model") == chosen.get("model") and p.get("role") in ("reasoner", "coder")
            runs.append(InferenceRun(
                task_id=ctx.task_id, task_type=task_type.value if task_type else "unknown",
                model_id=p.get("model", "?"), role=p.get("role", e.source), latency_ms=p.get("latency_ms", 0),
                input_tokens=p.get("input_tokens", 0), output_tokens=p.get("output_tokens", 0), success=ok,
                verifier_score=verification.score if (verification and is_chosen) else None,
                complexity=ctx.route.complexity if ctx.route else None, mode=ctx.request.mode.value,
                arm=arm, task_confidence=confidence,
            ))

        if verification is not None and chosen is not None and task_type is not None:
            for c in ctx.state.candidates:
                if c.get("model") not in self.registry.models:
                    continue
                quality = verification.score if c.get("claim_id") == chosen.get("claim_id") else \
                    verification.score * pair_agreement(c.get("answer", ""), chosen["answer"])
                latency = c.get("latency_ms") or next(
                    (r.latency_ms for r in runs if r.model_id == c.get("model") and r.success), 0)
                self.registry.record(c["model"], task_type, quality, latency)
        for r in runs:
            if not r.success and task_type is not None:
                self.registry.record(r.model_id, task_type, 0.0, r.latency_ms or 0)

        if self.telemetry is not None:
            try:
                await self.telemetry.record_runs(runs)
            except Exception:
                log.exception("telemetry failed")
        await self._save_task(ctx, response)

        if self.memory_compiler is not None and chosen is not None and verification is not None:
            try:
                objective = ctx.request.last_user_text[:4000]
                if ctx.sensitivity >= Sensitivity.SECRET:
                    objective = self.policy.redact(objective)  # never persist secrets in memory
                stored = await self.memory_compiler.compile(OutcomeRecord(
                    task_type=task_type.value,
                    objective=objective,
                    answer=response.answer if response else chosen["answer"],
                    success=verification.passed,
                    verified=verification.verified,
                    confidence=confidence or 0.0,
                    complexity=ctx.route.complexity,
                    strategy=[d.get("strategy", d.get("type", "")) for d in ctx.state.decisions if d.get("strategy")]
                    + [f"tool:{t}" for t in ctx.state.tools_used],
                    tools=ctx.state.tools_used,
                ))
                if stored:
                    await ctx.emit(EventType.MEMORY_STORED, "memory_compiler", {"items": [
                        {"id": m.id, "type": m.memory_type.value, "text": m.text, "status": m.status.value,
                         "importance": m.importance} for m in stored
                    ]})
                    if self.cache is not None and any(m.memory_type.value == "semantic" for m in stored):
                        self.cache.invalidate()  # knowledge changed
            except Exception:
                log.exception("memory compilation failed")

        if self.cache is not None and response is not None and self.config.semantic_cache:
            try:
                await self.cache.store(ctx.request, response, ctx.memory_ids)
            except Exception:
                log.exception("semantic cache store failed")

        self._tasks_since_refit += 1
        if self.telemetry is not None and self._tasks_since_refit >= self.config.refit_every:
            self._tasks_since_refit = 0
            try:
                self.learned.fit(await self.telemetry.recent_runs())
            except Exception:
                log.exception("learned router refit failed")


__all__ = ["GenerationFailed", "HydraKernel", "HydraTaskFailed", "KernelConfig", "NoModelAvailable"]
