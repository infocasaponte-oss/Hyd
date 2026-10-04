# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.runtime.policy import PolicyEngine, ToolPermission
from hydra.runtime.tools import ToolRegistry, Workspace
from hydra.runtime.sandbox import OciSandbox


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    output: str
    exit_code: int | None = None


class ToolRuntime:
    def __init__(
        self,
        workspace: Workspace,
        registry: ToolRegistry | None = None,
        policy: PolicyEngine | None = None,
        sandbox: OciSandbox | None = None,
    ):
        self.workspace = workspace
        self.registry = registry or ToolRegistry()
        self.policy = policy or PolicyEngine()
        self.sandbox = sandbox
        if sandbox is not None and sandbox.workspace != workspace.root:
            raise ValueError("sandbox workspace must match tool workspace")

    async def run(
        self,
        name: str,
        arguments: dict,
        permission: ToolPermission | None = None,
    ) -> ToolResult:
        permission = permission or ToolPermission()
        spec = self.registry.get(name)
        self.policy.authorize(spec, permission)

        if name == "workspace.list":
            path = self.workspace.resolve(arguments.get("path", "."))
            items = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
            return ToolResult(name, True, "\n".join(items))

        if name == "workspace.read":
            path = self.workspace.resolve(arguments["path"])
            if not path.is_file():
                raise ValueError("Not a file")
            limit = min(int(arguments.get("max_chars", 20_000)), 100_000)
            return ToolResult(name, True, path.read_text(encoding="utf-8")[:limit])

        if name == "workspace.search":
            query = str(arguments["query"])
            root = self.workspace.resolve(arguments.get("path", "."))
            hits = []
            for path in root.rglob("*"):
                if not path.is_file() or path.stat().st_size > 1_000_000:
                    continue
                try:
                    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                        if query in line:
                            hits.append(f"{path.relative_to(self.workspace.root)}:{line_no}:{line}")
                            if len(hits) >= 100:
                                return ToolResult(name, True, "\n".join(hits))
                except (UnicodeDecodeError, OSError):
                    continue
            return ToolResult(name, True, "\n".join(hits))

        if name == "python.test":
            target = self.workspace.resolve(arguments.get("path", "."))
            if self.sandbox is None:
                raise RuntimeError("python.test requires an isolated sandbox; host execution is disabled")
            relative = target.relative_to(self.workspace.root).as_posix()
            result = await self.sandbox.pytest(relative, read_only=True)
            return ToolResult(name, result.ok, result.output, result.exit_code)

        raise KeyError(name)
