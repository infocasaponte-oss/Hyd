# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from uuid import UUID

from hydra.core.durable_events import JsonlEventStore
from hydra.runtime.policy import ToolPermission
from hydra.runtime.tool_runtime import ToolResult, ToolRuntime


class AuditedToolRuntime:
    def __init__(self, runtime: ToolRuntime, events: JsonlEventStore):
        self.runtime = runtime
        self.events = events

    async def run(
        self,
        *,
        task_id: UUID,
        trace_id: str,
        name: str,
        arguments: dict,
        permission: ToolPermission | None = None,
    ) -> ToolResult:
        # Arguments are intentionally not persisted yet; they may contain sensitive content.
        self.events.append(
            event_type="hydra.tool.requested",
            aggregate_id=task_id,
            producer="hydra.tool_runtime",
            trace_id=trace_id,
            payload={"tool": name},
        )
        try:
            result = await self.runtime.run(name, arguments, permission)
        except Exception as exc:
            self.events.append(
                event_type="hydra.tool.failed",
                aggregate_id=task_id,
                producer="hydra.tool_runtime",
                trace_id=trace_id,
                payload={"tool": name, "error_type": type(exc).__name__},
            )
            raise
        self.events.append(
            event_type="hydra.tool.completed",
            aggregate_id=task_id,
            producer="hydra.tool_runtime",
            trace_id=trace_id,
            payload={"tool": name, "ok": result.ok, "exit_code": result.exit_code},
        )
        return result
