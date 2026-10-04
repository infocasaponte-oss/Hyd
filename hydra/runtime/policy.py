# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from pydantic import BaseModel

from hydra.runtime.tools import ToolRisk, ToolSpec


class ToolPermission(BaseModel):
    allow_execute: bool = False
    allow_write: bool = False
    allow_network: bool = False


class PolicyDenied(PermissionError):
    pass


class PolicyEngine:
    def authorize(self, spec: ToolSpec, permission: ToolPermission) -> None:
        if spec.network and not permission.allow_network:
            raise PolicyDenied("Network access denied")
        if spec.filesystem_write and not permission.allow_write:
            raise PolicyDenied("Filesystem write denied")
        if spec.risk == ToolRisk.WRITE and not permission.allow_write:
            raise PolicyDenied("Write tool denied")
        if spec.risk == ToolRisk.EXECUTE and not permission.allow_execute:
            raise PolicyDenied("Process execution denied")
