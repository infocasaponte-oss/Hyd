# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import asyncio
import hashlib
from uuid import uuid4

from hydra.core.inference_budget import inference_budget
from hydra.core.task_commit import CaptureUnitOfWork, TaskCommit
from hydra.core.native_contracts import HydraResult, HydraTask, Route, TaskStatus
from hydra.core.durable_events import JsonlEventStore
from hydra.scheduler.native_executor import ExecutionOutput, Executor
from hydra.registry.native import ModelRegistry
from hydra.observability.spans import SpanRecorder as CognitiveTracer
from hydra.scheduler.native import Planner
from hydra.providers.local_llm import LocalLLM
from hydra.router.native import CapabilityRouter
from hydra.deploy.bridge import RuntimeBridge
from hydra.core.native_state import validate_transition
from hydra.verification.verifier import Verifier


class HydraKernel:
    def __init__(
        self,
        router: CapabilityRouter | None = None,
        events: JsonlEventStore | None = None,
        planner: Planner | None = None,
        model_registry: ModelRegistry | None = None,
        runtime_bridge: RuntimeBridge | None = None,
        capture_uow: CaptureUnitOfWork | None = None,
        tracer: CognitiveTracer | None = None,
    ):
        self.router = router or CapabilityRouter()
        self.events = events or JsonlEventStore()
        self.planner = planner or Planner()
        self.model_registry = model_registry or ModelRegistry()
        self.runtime_bridge = runtime_bridge
        self.capture_uow = capture_uow
        self.tracer = tracer or CognitiveTracer()

    def _transition(self, task: HydraTask, target: TaskStatus, trace_id: str) -> None:
        validate_transition(task.status, target)
        previous = task.status
        task.status = target
        self.events.append(
            event_type="hydra.task.transitioned",
            aggregate_id=task.id,
            producer="hydra.kernel",
            trace_id=trace_id,
            payload={"from": previous.value, "to": target.value},
        )

    def prepare(self, task: HydraTask) -> tuple[str, Route]:
        trace_id = uuid4().hex
        self.events.append(
            event_type="hydra.task.created",
            aggregate_id=task.id,
            producer="hydra.kernel",
            trace_id=trace_id,
            payload={"goal": task.goal, "budget": task.budget.model_dump()},
        )
        self._transition(task, TaskStatus.ROUTING, trace_id)
        with self.tracer.span(
            "routing",
            trace_id=trace_id,
            task_id=task.id,
        ):
            route = self.router.route(task)
        self.events.append(
            event_type="hydra.route.completed",
            aggregate_id=task.id,
            producer="hydra.router",
            trace_id=trace_id,
            payload=route.model_dump(),
        )
        return trace_id, route

    async def run(self, task: HydraTask, llm: LocalLLM) -> HydraResult:
        trace_id, route = self.prepare(task)

        self._transition(task, TaskStatus.PLANNING, trace_id)
        with self.tracer.span(
            "planning",
            trace_id=trace_id,
            task_id=task.id,
            attributes={"capability": route.capability},
        ):
            plan = self.planner.build(task, route)
        self.events.append(
            event_type="hydra.plan.created",
            aggregate_id=task.id,
            producer="hydra.planner",
            trace_id=trace_id,
            payload=plan.model_dump(mode="json"),
        )

        self._transition(task, TaskStatus.EXECUTING, trace_id)
        try:
            with inference_budget(task.budget.max_model_calls):
                async with asyncio.timeout(task.budget.max_seconds):
                    with self.tracer.span(
                        "execution",
                        trace_id=trace_id,
                        task_id=task.id,
                        attributes={"capability": route.capability},
                    ):
                        executor = Executor(llm, self.model_registry, Verifier())
                        if self.runtime_bridge is not None and not route.needs_tools:
                            try:
                                runtime_output = await self.runtime_bridge.execute(
                                    task_id=task.id,
                                    trace_id=trace_id,
                                    capability=route.capability,
                                    prompt=task.goal,
                                    max_tokens=task.budget.max_output_tokens,
                                )
                            except LookupError as exc:
                                self.events.append(
                                    event_type="hydra.runtime.logical_fallback",
                                    aggregate_id=task.id,
                                    producer="hydra.kernel",
                                    trace_id=trace_id,
                                    payload={
                                        "capability": route.capability,
                                        "reason": type(exc).__name__,
                                    },
                                )
                                output = await executor.execute(
                                    plan,
                                    task.budget.max_output_tokens,
                                    max_model_calls=task.budget.max_model_calls,
                                )
                            else:
                                output = ExecutionOutput(
                                    answer=runtime_output.answer,
                                    model_id=runtime_output.primary_variant_id,
                                    verification=None,
                                )
                        else:
                            output = await executor.execute(
                                plan,
                                task.budget.max_output_tokens,
                                max_model_calls=task.budget.max_model_calls,
                            )
        except Exception:
            self._transition(task, TaskStatus.FAILED, trace_id)
            self.events.append(
                event_type="hydra.task.failed",
                aggregate_id=task.id,
                producer="hydra.kernel",
                trace_id=trace_id,
                payload={"capability": route.capability},
            )
            raise

        self.events.append(
            event_type="hydra.model.completed",
            aggregate_id=task.id,
            producer="hydra.executor",
            trace_id=trace_id,
            payload={"model_id": output.model_id},
        )

        confidence = 0.55
        if route.needs_verification:
            self._transition(task, TaskStatus.VERIFYING, trace_id)
            with self.tracer.span(
                "verification",
                trace_id=trace_id,
                task_id=task.id,
                attributes={"capability": route.capability},
            ):
                verification = output.verification or Verifier().verify_text(output.answer)
            self.events.append(
                event_type="hydra.verification.completed",
                aggregate_id=task.id,
                producer="hydra.verifier",
                trace_id=trace_id,
                payload=verification.model_dump(),
            )
            confidence = verification.confidence
            self._transition(task, TaskStatus.SYNTHESIZING, trace_id)
        else:
            self._transition(task, TaskStatus.SYNTHESIZING, trace_id)

        if self.capture_uow is None:
            self._transition(task, TaskStatus.COMPLETED, trace_id)
            result = HydraResult(
                task_id=task.id,
                status=task.status,
                answer=output.answer,
                confidence=confidence,
                trace_id=trace_id,
                metadata={"model_id": output.model_id, "capability": route.capability},
            )
            self.events.append(
                event_type="hydra.task.completed",
                aggregate_id=task.id,
                producer="hydra.kernel",
                trace_id=trace_id,
                payload={"confidence": confidence, "model_id": output.model_id},
            )
            return result

        validate_transition(task.status, TaskStatus.COMPLETED)
        result = HydraResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            answer=output.answer,
            confidence=confidence,
            trace_id=trace_id,
            metadata={"model_id": output.model_id, "capability": route.capability},
        )
        answer_hash = hashlib.sha256(output.answer.encode()).hexdigest()
        corpus_payload = task.metadata.get("corpus_record")
        with self.tracer.span(
            "capture",
            trace_id=trace_id,
            task_id=task.id,
            attributes={"capability": route.capability},
        ):
            self.capture_uow.commit_terminal(
                TaskCommit(
                    task_id=task.id,
                    trace_id=trace_id,
                    status=TaskStatus.COMPLETED.value,
                    result=result.model_dump(mode="json"),
                ),
                event_payload={
                    "event_type": "hydra.task.completed",
                    "producer": "hydra.kernel",
                    "payload": {
                        "confidence": confidence,
                        "model_id": output.model_id,
                    },
                },
                provenance_payload={
                    "action": "task.completed",
                    "inputs": {"capability": route.capability},
                    "outputs": {
                        "answer_sha256": answer_hash,
                        "model_id": output.model_id,
                    },
                },
                corpus_payload=corpus_payload,
            )
        task.status = TaskStatus.COMPLETED
        return result
