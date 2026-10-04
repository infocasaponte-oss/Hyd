# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from hydra.tools.task_workspace import ConfinedRoot


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    EXECUTE = "execute"
    WRITE = "write"


class ToolSpec(BaseModel):
    name: str
    risk: ToolRisk
    network: bool = False
    filesystem_write: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            "workspace.list": ToolSpec(name="workspace.list", risk=ToolRisk.READ_ONLY),
            "workspace.read": ToolSpec(name="workspace.read", risk=ToolRisk.READ_ONLY),
            "workspace.search": ToolSpec(name="workspace.search", risk=ToolRisk.READ_ONLY),
            "python.test": ToolSpec(name="python.test", risk=ToolRisk.EXECUTE, timeout_seconds=120),
        }

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)


# F4e: path confinement moved to the platform (used by the coding loop and patching).
Workspace = ConfinedRoot
