# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import json
import os
from pathlib import Path

from hydra.core.request_budget import RequestBudget
from hydra.core.runtime_paths import runtime_path
from hydra.providers.local_llm import LocalLLM


class GlossaryStore:
    def __init__(self, root: str | Path = runtime_path("glossaries")):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, glossary_id: str) -> Path:
        safe = "".join(c for c in glossary_id if c.isalnum() or c in "-_.")
        if not safe or safe != glossary_id:
            raise ValueError("Invalid glossary id")
        base = os.path.realpath(self.root)
        candidate = os.path.realpath(os.path.join(base, f"{safe}.json"))
        if not candidate.startswith(base.rstrip(os.sep) + os.sep):
            raise ValueError("Glossary path escapes its root")
        return Path(candidate)

    def save(self, glossary_id: str, terms: dict[str, str]) -> dict:
        payload = {"id": glossary_id, "terms": dict(sorted(terms.items()))}
        self._path(glossary_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def load(self, glossary_id: str) -> dict[str, str]:
        path = self._path(glossary_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")).get("terms", {})


def split_text(text: str, max_chars: int = 6000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks, current, size = [], [], 0
    for paragraph in text.split("\n\n"):
        addition = len(paragraph) + (2 if current else 0)
        if current and size + addition > max_chars:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, size = [], 0
            chunks.extend(paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars))
        else:
            current.append(paragraph)
            size += addition
    if current:
        chunks.append("\n\n".join(current))
    return chunks


class TranslationService:
    def __init__(self, llm: LocalLLM, budget: RequestBudget, glossaries: GlossaryStore):
        self.llm, self.budget, self.glossaries = llm, budget, glossaries

    async def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
        glossary_id: str | None = None,
    ) -> str:
        self.budget.validate_input(text)
        chunks = split_text(text)
        self.budget.validate_chunks(len(chunks))
        terms = self.glossaries.load(glossary_id) if glossary_id else {}
        glossary = "\n".join(f"- {a} => {b}" for a, b in terms.items()) or "(none)"
        source = source_language or "detect automatically"
        system = (
            f"Translate faithfully from {source} to {target_language}. "
            "Return only translated content. Preserve Markdown, URLs, numbers and code. "
            "Do not translate code identifiers. Mandatory glossary:\n" + glossary
        )
        result = []
        for chunk in chunks:
            result.append(
                await self.llm.chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": chunk}],
                    temperature=0.0,
                    max_tokens=self.budget.max_output_tokens,
                )
            )
        return "\n\n".join(result)
