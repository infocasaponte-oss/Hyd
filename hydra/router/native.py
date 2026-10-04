# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.core.native_contracts import HydraTask, Route, TaskType


class CapabilityRouter:
    """Deterministic System-1 router; replaceable later by HYDRA-Router."""

    def route(self, task: HydraTask) -> Route:
        text = task.goal.lower()

        if task.task_type is not None:
            kind = task.task_type
        elif any(word in text for word in ("translate", "traduce", "traducir", "translation")):
            kind = TaskType.TRANSLATION
        elif any(word in text for word in ("bug", "debug", "python", "código", "code", "test")):
            kind = TaskType.CODING
        elif any(word in text for word in ("research", "investiga", "fuentes", "sources")):
            kind = TaskType.RESEARCH
        elif any(word in text for word in ("razona", "reason", "demuestra", "prove")):
            kind = TaskType.REASONING
        else:
            kind = TaskType.CHAT

        mapping = {
            TaskType.CHAT: ("chat.multilingual", False, False),
            TaskType.TRANSLATION: ("language.translate", False, False),
            TaskType.CODING: ("coding.general", True, True),
            TaskType.RESEARCH: ("research.general", True, True),
            TaskType.REASONING: ("reasoning.general", True, False),
            TaskType.TOOL_USE: ("tool.execute", True, True),
        }
        capability, verify, tools = mapping[kind]
        return Route(
            task_type=kind,
            capability=capability,
            needs_verification=verify,
            needs_tools=tools,
            parallelism=1,
            confidence=0.90 if task.task_type is not None else 0.75,
        )
