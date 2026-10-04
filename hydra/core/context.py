# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Per-task execution context. Every state change is an event; the blackboard is its projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from hydra.blackboard.projector import BlackboardProjector
from hydra.blackboard.state import BlackboardState
from hydra.bus.base import EventBus
from hydra.core.budget import BudgetTracker
from hydra.core.contracts import HydraRequest, RoutingDecision
from hydra.core.events import EventType, HydraEvent
from hydra.core.state import TaskStateMachine, TaskStatus
from hydra.registry.models import ModelProfile
from hydra.tools.definitions import ToolContext
from hydra.world.state import WorldState


@dataclass
class TaskContext:
    request: HydraRequest
    bus: EventBus
    budget: BudgetTracker
    task_id: UUID = field(default_factory=uuid4)
    trace_id: str | None = None

    route: RoutingDecision | None = None
    ranked: list[ModelProfile] = field(default_factory=list)
    tool_ctx: ToolContext | None = None
    memory_lines: list[str] = field(default_factory=list)
    web_context: list[str] = field(default_factory=list)
    web_sources: list[str] = field(default_factory=list)
    knowledge_coverage: float | None = None

    state: BlackboardState = field(default_factory=BlackboardState)
    machine: TaskStateMachine = field(default_factory=TaskStateMachine)
    failed_models: set[str] = field(default_factory=set)
    events: list[HydraEvent] = field(default_factory=list)

    sensitivity: int = 0
    conversation: list[dict] | None = None
    """Conversation as sent to workers (possibly compressed). None -> request messages."""
    compressed_block: str = ""
    world: WorldState = field(default_factory=WorldState)
    memory_ids: list[str] = field(default_factory=list)
    shadow: bool = False
    learn: bool = True
    prompts: dict[str, str] = field(default_factory=dict)
    """Per-role system prompt overrides (HYDRA Lab experiments)."""
    degradations: list[str] = field(default_factory=list)
    """Graceful-degradation notes surfaced to the user as uncertainties."""

    def messages_for_workers(self) -> list[dict]:
        if self.conversation is not None:
            return [dict(m) for m in self.conversation]
        return [m.to_provider() for m in self.request.messages]

    _projector: BlackboardProjector = field(default_factory=BlackboardProjector)

    async def emit(self, type_: EventType, source: str, payload: dict | None = None) -> HydraEvent:
        event = HydraEvent(task_id=self.task_id, type=type_, source=source,
                           payload=payload or {}, trace_id=self.trace_id)
        self.events.append(event)
        self._projector.apply(self.state, event)
        await self.bus.publish(event)
        return event

    def observe(self, event: HydraEvent) -> None:
        """Apply an event published by another component (e.g. the tool executor)."""
        if event.task_id == self.task_id:
            self._projector.apply(self.state, event)

    async def status(self, new: TaskStatus) -> None:
        self.machine.to(new)
        await self.emit(EventType.TASK_STATUS, "kernel", {"status": new.value})
