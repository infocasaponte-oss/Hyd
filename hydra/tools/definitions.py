# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""A model never executes code. It only requests a tool; the runtime decides."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]

    timeout_seconds: int = 30
    risk_level: int = Field(default=1, ge=1, le=5)

    requires_network: bool = False
    requires_filesystem: bool = False
    writes: bool = False


class WorkerCapabilities(BaseModel):
    """What a worker is allowed to do, regardless of what the model asks for."""

    tools: set[str] = Field(default_factory=set)
    filesystem_paths: list[str] = Field(default_factory=list)
    network_domains: list[str] = Field(default_factory=list)
    public_web: bool = False
    max_runtime_seconds: int = 60


class ToolContext(BaseModel):
    task_id: UUID
    private: bool = False
    allow_high_risk_tools: bool = False
    capabilities: WorkerCapabilities = Field(default_factory=WorkerCapabilities)
    workspace: Path = Path("workspace")
    approved: set[str] = Field(default_factory=set)
    """Tools the user approved for this request."""
    shadow: bool = False
    """Shadow execution (HYDRA Lab): side effects are forbidden."""

    model_config = {"arbitrary_types_allowed": True}


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "unknown"
    id: str | None = None


class ToolResult(BaseModel):
    name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[Any]]


class RegisteredTool:
    def __init__(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.definition = definition
        self.handler = handler
