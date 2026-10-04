# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import uuid
from typing import Any

from hydra.core.context import TaskContext
from hydra.core.errors import ErrorKind, ModelError
from hydra.core.events import EventType
from hydra.memory.context import ContextBudget, ContextCompiler
from hydra.registry.models import ModelProfile
from hydra.scheduler.invoker import ModelInvoker


class Worker:
    role = "worker"
    system_prompt = ""

    def __init__(self, invoker: ModelInvoker, compiler: ContextCompiler | None = None) -> None:
        self.invoker = invoker
        self.compiler = compiler or ContextCompiler()

    def build_messages(self, ctx: TaskContext, model: ModelProfile, generation_tokens: int = 2048,
                       extra_system: str = "", tool_results: list[str] | None = None,
                       messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """``messages`` overrides the conversation (e.g. a research sub-question)."""
        budget = ContextBudget.for_window(model.context_window, generation_tokens)
        system = self.prompt_for(ctx) + ("\n\n" + extra_system if extra_system else "")
        if model.identity_context:
            system = model.identity_context + "\n\n" + system
        if ctx.compressed_block and messages is None:
            system += "\n\n" + ctx.compressed_block
        return self.compiler.compile(
            budget,
            system=system.strip(),
            messages=messages if messages is not None else ctx.messages_for_workers(),
            memories=ctx.memory_lines,
            tool_results=tool_results,
            documents=ctx.web_context,
            working_state=None if ctx.world.empty else "WORLD STATE:\n" + ctx.world.render(),
        )

    @staticmethod
    def reasoning_level(ctx: TaskContext) -> str:
        """Think hard only when the route needs reasoning (thinking models are slow)."""
        return "high" if ctx.route is not None and ctx.route.requires_reasoning else "off"

    def prompt_for(self, ctx: TaskContext) -> str:
        """System prompt, overridable per experiment (HYDRA Lab: 'prompt.<role>')."""
        return ctx.prompts.get(self.role, self.system_prompt)

    @staticmethod
    def require_answer(ctx: TaskContext, model_id: str, content: str) -> None:
        """An empty answer is a failed attempt, not a candidate: exclude that model from retries."""
        if not content.strip():
            ctx.failed_models.add(model_id)
            raise ModelError(f"{model_id}: empty answer", ErrorKind.MODEL_REFUSAL)

    @staticmethod
    async def add_evidence(ctx: TaskContext, claim_id: str, source_type: str, source_ref: str,
                           strength: float, supports: bool) -> str:
        ev_id = f"ev-{uuid.uuid4().hex[:10]}"
        await ctx.emit(EventType.EVIDENCE_ADDED, source_type, {
            "id": ev_id, "claim_id": claim_id, "source_type": source_type, "source_ref": source_ref,
            "strength": round(max(0.0, min(1.0, strength)), 4), "supports": supports,
        })
        return ev_id


def claim_id_for(model_id: str, index: int = 0) -> str:
    return f"candidate:{model_id}:{index}"
