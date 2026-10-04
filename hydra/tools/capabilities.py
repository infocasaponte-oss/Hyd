# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Capability-scoped tools: even if a model hallucinates ``rm -rf /`` it has no capability to do it."""

from __future__ import annotations

from hydra.core.contracts import RoutingDecision, TaskType
from hydra.tools.definitions import WorkerCapabilities

CODER = WorkerCapabilities(
    tools={"python.execute", "filesystem.read", "filesystem.write", "git.diff", "git.apply_patch", "json.validate"},
    filesystem_paths=["."],
    network_domains=[],
    max_runtime_seconds=120,
)

ANALYST = WorkerCapabilities(
    tools={"python.execute", "json.validate", "sql.query_readonly", "filesystem.read", "search.query"},
    filesystem_paths=["."],
    max_runtime_seconds=60,
)

RESEARCHER = WorkerCapabilities(
    tools={"http.fetch", "web.search", "web.read", "search.query", "filesystem.read"},
    public_web=True,
    filesystem_paths=["."],
    network_domains=["wikipedia.org", "arxiv.org", "github.com", "python.org", "docs.python.org"],
    max_runtime_seconds=60,
)

NONE = WorkerCapabilities(tools=set(), max_runtime_seconds=10)


def capabilities_for(route: RoutingDecision, network_domains: list[str] | None = None) -> WorkerCapabilities:
    if not route.requires_tools and route.task_type not in (TaskType.RESEARCH, TaskType.TOOL_USE):
        return NONE
    match route.task_type:
        case TaskType.CODING:
            caps = CODER
        case TaskType.RESEARCH:
            caps = RESEARCHER
        case TaskType.REASONING | TaskType.TOOL_USE:
            caps = ANALYST
        case _:
            caps = ANALYST
    caps = caps.model_copy(deep=True)
    if network_domains is not None:
        caps.network_domains = list(network_domains)
    return caps
