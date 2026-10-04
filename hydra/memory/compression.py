# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Adaptive context compression: raw context -> facts / decisions / open questions / excerpts,
keeping pointers to the original so detail can be recovered when needed."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from hydra.memory.compiler import extract_facts
from hydra.memory.context import count_tokens

SENT = re.compile(r"(?<=[.!?])\s+|\n+")
DECISION = re.compile(r"(?i)\b(decid|acord|vamos a|we will|we'll|let's|usaremos|we decided|agreed|elegimos|chose)\w*")
IMPORTANT = re.compile(r"(?i)\b(error|bug|must|debe|important|importante|requisito|requirement|deadline|"
                       r"nunca|never|siempre|always|puerto|port|versión|version)\b|\d")


class Pointer(BaseModel):
    message: int
    start: int
    end: int


class Item(BaseModel):
    text: str
    pointer: Pointer


class CompressedState(BaseModel):
    facts: list[Item] = Field(default_factory=list)
    decisions: list[Item] = Field(default_factory=list)
    open_questions: list[Item] = Field(default_factory=list)
    excerpts: list[Item] = Field(default_factory=list)
    compressed_messages: int = 0
    original_tokens: int = 0
    compressed_tokens: int = 0

    def render(self) -> str:
        parts = []
        for title, items in (("FACTS", self.facts), ("DECISIONS", self.decisions),
                             ("OPEN QUESTIONS", self.open_questions), ("KEY EXCERPTS", self.excerpts)):
            if items:
                parts.append(title + ":\n" + "\n".join(
                    f"- {i.text} [ref m{i.pointer.message}:{i.pointer.start}-{i.pointer.end}]" for i in items))
        return (f"COMPRESSED EARLIER CONVERSATION ({self.compressed_messages} messages):\n"
                + "\n".join(parts)) if parts else ""


def _tokens(text: str) -> int:
    return count_tokens(text)


def compress(messages: list[dict[str, Any]], keep_last: int, budget_tokens: int,
             max_per_section: int = 12) -> tuple[CompressedState | None, list[dict[str, Any]]]:
    """Compress all but the last ``keep_last`` messages if the conversation exceeds the budget."""
    total = sum(_tokens(str(m.get("content", ""))) for m in messages)
    if total <= budget_tokens or len(messages) <= keep_last:
        return None, messages
    old, recent = messages[:-keep_last], messages[-keep_last:]
    state = CompressedState(compressed_messages=len(old), original_tokens=total)
    seen: set[str] = set()
    for idx, m in enumerate(old):
        content = str(m.get("content", ""))
        pos = 0
        for sent in SENT.split(content):
            s = sent.strip()
            start = content.find(s, pos) if s else pos
            pos = start + len(s) if start >= 0 else pos
            if len(s) < 8 or s.lower() in seen:
                continue
            ptr = Pointer(message=idx, start=max(0, start), end=max(0, start) + len(s))
            item = Item(text=s[:300], pointer=ptr)
            if extract_facts(s):
                bucket = state.facts
            elif DECISION.search(s):
                bucket = state.decisions
            elif s.endswith("?"):
                bucket = state.open_questions
            elif IMPORTANT.search(s):
                bucket = state.excerpts
            else:
                continue
            if len(bucket) < max_per_section:
                bucket.append(item)
                seen.add(s.lower())
    state.compressed_tokens = _tokens(state.render()) + sum(_tokens(str(m.get("content", ""))) for m in recent)
    return state, recent


def expand(messages: list[dict[str, Any]], pointer: Pointer, context_chars: int = 400) -> str:
    """Recover the original detail behind a compressed item."""
    content = str(messages[pointer.message].get("content", ""))
    return content[max(0, pointer.start - context_chars): pointer.end + context_chars]
