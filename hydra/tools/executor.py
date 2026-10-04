# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""LLM -> tool intent -> schema validation -> permission policy -> risk -> sandbox."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

from hydra.bus.base import EventBus
from hydra.core.events import EventType, HydraEvent
from hydra.tools.definitions import ToolCall, ToolContext, ToolResult
from hydra.tools.policy import ToolPolicyEngine
from hydra.tools.registry import ToolRegistry
from hydra.tools.schema import validate

Emit = Callable[[EventType, str, dict], Awaitable[object]]


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: ToolPolicyEngine, event_bus: EventBus,
                 simulator=None, secrets=None, policy_dsl=None) -> None:
        self.registry = registry
        self.policy = policy
        self.event_bus = event_bus
        self.simulator = simulator
        self.secrets = secrets
        """Secrets Broker: resolves secret:// references right before execution, redacts outputs."""
        self.policy_dsl = policy_dsl
        """Declarative Policy DSL evaluated on top of the Policy Kernel."""
        """Optional Simulation Engine: predicts the effect of risky actions before running them."""

    def _bus_emit(self, ctx: ToolContext) -> Emit:
        async def emit(type_: EventType, source: str, payload: dict) -> None:
            await self.event_bus.publish(HydraEvent(task_id=ctx.task_id, type=type_, source=source, payload=payload))
        return emit

    async def execute(self, call: ToolCall, ctx: ToolContext, emit: Emit | None = None) -> ToolResult:
        """``emit`` lets a task route tool events through its own blackboard projection."""
        emit = emit or self._bus_emit(ctx)
        await emit(EventType.TOOL_REQUESTED, call.requested_by,
                   {"tool": call.name, "arguments": _jsonable(call.arguments)})

        async def fail(type_: EventType, error: str, kind: str, tool: str | None = None) -> ToolResult:
            await emit(type_, "tool_executor",
                       {"tool": tool or call.name, "error": error, "kind": kind, "requested_by": call.requested_by})
            return ToolResult(name=tool or call.name, success=False, error=error)

        tool = self.registry.get(call.name)
        if tool is None:
            return await fail(EventType.TOOL_FAILED, f"unknown tool '{call.name}'", "hallucinated_tool")
        name = tool.definition.name

        errors = validate(call.arguments, tool.definition.input_schema)
        if errors:
            return await fail(EventType.TOOL_FAILED, "invalid arguments: " + "; ".join(errors),
                              "invalid_arguments", name)

        if self.policy_dsl is not None:
            verdict = self.policy_dsl.evaluate({
                "tool": name, "sandboxed": name in ("python.execute", "python.run_tests"),
                "network": tool.definition.requires_network, "writes": tool.definition.writes,
                "risk_level": tool.definition.risk_level, "private": ctx.private, "shadow": ctx.shadow})
            if verdict.effect == "deny":
                return await fail(EventType.TOOL_DENIED, f"policy rule {verdict.matched}: {verdict.reasons}",
                                  "permission", name)

        decision = await self.policy.evaluate(tool, call, ctx)
        if not decision.allowed:
            if decision.kind == "needs_confirmation":
                await emit(EventType.TOOL_DENIED, "policy_kernel", {
                    "tool": name, "error": decision.reason, "kind": "needs_confirmation",
                    "arguments": _jsonable(call.arguments), "requested_by": call.requested_by})
                return ToolResult(name=name, success=False, error=decision.reason)
            return await fail(EventType.TOOL_DENIED, decision.reason, "permission", name)

        if self.simulator is not None and self.simulator.should_simulate(tool.definition):
            sim = await self.simulator.simulate(call, tool.definition, ctx)
            await emit(EventType.SIMULATION_COMPLETED, "simulator", sim.model_dump())
            if not sim.ok:
                return await fail(EventType.TOOL_FAILED, f"simulation rejected the action: {sim.summary}",
                                  "simulation", name)

        await emit(EventType.TOOL_STARTED, "tool_executor", {"tool": name})
        timeout = min(tool.definition.timeout_seconds, ctx.capabilities.max_runtime_seconds)
        started = time.perf_counter()
        arguments = call.arguments
        if self.secrets is not None:
            try:
                arguments = self.secrets.inject(arguments, tool=name, principal=call.requested_by,
                                                task_id=str(ctx.task_id))
            except (PermissionError, KeyError) as exc:
                return await fail(EventType.TOOL_DENIED, f"secret broker: {exc}", "permission", name)
        try:
            output = await asyncio.wait_for(tool.handler(arguments, ctx), timeout=timeout)
        except asyncio.TimeoutError:
            return await fail(EventType.TOOL_FAILED, f"timeout after {timeout}s", "timeout", name)
        except Exception as exc:
            return await fail(EventType.TOOL_FAILED, f"{type(exc).__name__}: {exc}", "tool_error", name)

        duration = (time.perf_counter() - started) * 1000
        output = _jsonable(output)
        if tool.definition.requires_network:  # external data is never an instruction
            from hydra.governance.boundary import sanitize_tool_output
            output = sanitize_tool_output(name, output, external=True)
        if self.secrets is not None:
            output = self.secrets.redact(output)
        success = not (isinstance(output, dict) and output.get("exit_code", 0) != 0)
        await emit(EventType.TOOL_COMPLETED, "tool_executor",
                   {"tool": name, "arguments": _jsonable(call.arguments), "result": output,
                    "success": success, "duration_ms": round(duration, 2), "requested_by": call.requested_by})
        return ToolResult(name=name, success=success, output=output, duration_ms=duration)
