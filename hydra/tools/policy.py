# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Tool policy lives in code, never in the prompt."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from hydra.policy.kernel import PolicyKernel
from hydra.tools.definitions import RegisteredTool, ToolCall, ToolContext


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str = ""
    kind: str = "permission"  # permission | needs_confirmation


def resolve_in(base: Path, candidate: str) -> Path | None:
    """Resolve ``candidate`` inside ``base``; None if it escapes."""
    base = base.resolve()
    target = (base / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def allowed_path(ctx: ToolContext, candidate: str) -> Path | None:
    roots = ctx.capabilities.filesystem_paths or [str(ctx.workspace)]
    for root in roots:
        root_path = Path(root)
        if not root_path.is_absolute():
            root_path = ctx.workspace / root_path
        if (p := resolve_in(root_path, candidate)) is not None:
            return p
    return None


def allowed_domain(ctx: ToolContext, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in ctx.capabilities.network_domains)


class ToolPolicyEngine:
    def __init__(self, kernel: PolicyKernel | None = None) -> None:
        self.kernel = kernel

    async def evaluate(self, tool: RegisteredTool, call: ToolCall, ctx: ToolContext) -> PolicyDecision:
        d = tool.definition

        if d.name not in ctx.capabilities.tools:
            return PolicyDecision(allowed=False, reason=f"capability '{d.name}' not granted to worker")

        if ctx.shadow and (d.writes or d.requires_network):
            return PolicyDecision(allowed=False, reason="side effects are disabled in shadow execution")

        if self.kernel is not None:
            verdict = self.kernel.check_tool(d.name, d.risk_level, d.writes, ctx.approved)
            if not verdict.allowed:
                return PolicyDecision(allowed=False, reason=verdict.reason,
                                      kind="needs_confirmation" if verdict.needs_confirmation else "permission")
            if verdict.allowed and d.name in ctx.approved:
                ctx = ctx.model_copy(update={"allow_high_risk_tools": True})

        if ctx.private and d.requires_network:
            return PolicyDecision(allowed=False, reason="network tools are forbidden in private mode")

        if d.risk_level >= 4 and not ctx.allow_high_risk_tools:
            return PolicyDecision(allowed=False, reason=f"risk level {d.risk_level} requires explicit approval")

        if d.requires_filesystem and (path := call.arguments.get("path")) is not None:
            if allowed_path(ctx, str(path)) is None:
                return PolicyDecision(allowed=False, reason=f"path outside allowed scope: {path}")

        if d.requires_network and (url := call.arguments.get("url")) is not None:
            if d.name == "web.read" and ctx.capabilities.public_web:
                # web.read pins a public IP and checks every redirect. This
                # grant never broadens the older unrestricted http.fetch tool.
                return PolicyDecision(allowed=True)
            if not allowed_domain(ctx, str(url)):
                return PolicyDecision(allowed=False, reason=f"domain not allowed: {url}")

        return PolicyDecision(allowed=True)
