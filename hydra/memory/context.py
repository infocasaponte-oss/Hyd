# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Context compiler: HYDRA manages context the way an OS manages RAM."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def truncate(text: str, tokens: int) -> str:
    limit = tokens * 4
    return text if len(text) <= limit else text[: max(0, limit - 20)] + "\n…[truncated]"


class ContextBudget(BaseModel):
    total_tokens: int
    system_tokens: int
    user_tokens: int
    working_tokens: int
    memory_tokens: int
    document_tokens: int
    tool_tokens: int
    generation_tokens: int

    @classmethod
    def for_window(cls, window: int, generation: int = 2048) -> ContextBudget:
        """Split a context window: system 3%, user 5%, working 6%, tools 3%, memory 9%,
        documents 31%, generation as requested, rest reserved."""
        gen = min(generation, window // 4)
        return cls(
            total_tokens=window,
            system_tokens=max(256, int(window * 0.03)),
            user_tokens=max(512, int(window * 0.05)),
            working_tokens=max(256, int(window * 0.06)),
            memory_tokens=max(256, int(window * 0.09)),
            document_tokens=int(window * 0.31),
            tool_tokens=max(256, int(window * 0.03)),
            generation_tokens=gen,
        )


class ContextCompiler:
    def compile(
        self,
        budget: ContextBudget,
        system: str,
        messages: list[dict[str, Any]],
        memories: list[str] | None = None,
        tool_results: list[str] | None = None,
        working_state: str | None = None,
        documents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        sys_parts = [truncate(system, budget.system_tokens)]

        def pack(title: str, items: list[str] | None, tokens: int) -> None:
            if not items:
                return
            out, used = [], 0
            for it in items:
                t = count_tokens(it)
                if used + t > tokens:
                    # Oversized first documents must not disappear entirely.
                    remaining = tokens - used
                    if remaining > 32:
                        out.append(f"- {truncate(it, remaining)}")
                    break
                out.append(f"- {it}")
                used += t
            if out:
                sys_parts.append(f"{title}:\n" + "\n".join(out))

        pack("RELEVANT MEMORY (may be unverified; prefer evidence)", memories, budget.memory_tokens)
        pack("DOCUMENTS", documents, budget.document_tokens)
        pack("TOOL RESULTS", tool_results, budget.tool_tokens)
        if working_state:
            sys_parts.append("WORKING STATE:\n" + truncate(working_state, budget.working_tokens))

        # Keep the most recent conversation turns that fit the user budget.
        kept: list[dict[str, Any]] = []
        used = 0
        for m in reversed(messages):
            t = count_tokens(str(m.get("content", "")))
            if kept and used + t > budget.user_tokens:
                break
            kept.append({**m, "content": truncate(str(m.get("content", "")), budget.user_tokens)})
            used += t
        kept.reverse()

        return [{"role": "system", "content": "\n\n".join(sys_parts)}, *kept]
