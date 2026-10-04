# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Translation Engine: ``language.translate`` as a first-class HYDRA capability.

    language.detect · translate.<src>-<dst> · translation.technical / legal / code-aware / document

* persistent glossaries (World Model -> "Modelo do Mundo") enforced and *verified*
  (a glossary term missing in the output triggers one corrective retry),
* code-aware: fenced code blocks and inline code are never translated,
* whole documents are chunked by paragraphs (keeping order and structure),
* every translation becomes a TRANSLATION corpus candidate with glossary compliance as
  its verification score. A small dedicated translator can replace the main model later
  without changing the API."""

from __future__ import annotations

import re
import time
from pathlib import Path

from pydantic import BaseModel, Field

from hydra.core.docstore import DocumentStore, KeyedModels
from hydra.core.contracts import ExecutionMode, HydraRequest, Message, ModelRequest, RoutingDecision, TaskType
from hydra.language import LANGUAGE_NAMES, detect_language, normalize_language
from hydra.core.request_budget import RequestBudget

CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]+`")

SYSTEM = ("You are a professional translator. Translate the user's text from {src} to {dst}.\n"
          "Rules: preserve meaning, tone, formatting, numbers, URLs and placeholders like ⟦0⟧ exactly.\n"
          "Never translate code identifiers.{domain}\nUse this mandatory glossary when applicable:\n{glossary}\n"
          "Return ONLY the translated text, no explanations.")
DOMAIN_HINT = {"technical": " Use precise technical terminology.",
               "legal": " Use formal legal register; do not simplify legal terms.",
               "code-aware": " Comments and strings may be translated; code must remain unchanged.",
               "general": ""}


class TranslationRequest(BaseModel):
    text: str
    target_language: str
    source_language: str | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    glossary_name: str | None = None
    domain: str = "general"
    model: str | None = None


class TranslationResult(BaseModel):
    source_language: str
    target_language: str
    translation: str
    model: str | None = None
    glossary_compliance: float = 1.0
    missing_terms: list[str] = Field(default_factory=list)
    chunks: int = 1
    latency_ms: float = 0.0
    corpus_record: str | None = None


class GlossaryStore:
    """Glossaries in the ``glossaries.json`` document (``hydra.core.docstore``)."""

    def __init__(self, path: Path, docs: DocumentStore | None = None) -> None:
        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("glossaries.json", path))

    @property
    def data(self) -> dict[str, dict[str, str]]:
        return self._registry.all()

    def get(self, name: str) -> dict[str, str]:
        return dict(self.data.get(name, {}))

    def put(self, name: str, terms: dict[str, str]) -> dict[str, str]:
        return self._registry.change(name, lambda current: {**(current or {}), **terms})

    def names(self) -> list[str]:
        return sorted(self.data)


def protect(text: str) -> tuple[str, list[str]]:
    """Replace code with placeholders so the model cannot translate it."""
    slots: list[str] = []

    def keep(m):
        slots.append(m.group(0))
        return f"⟦{len(slots) - 1}⟧"
    return INLINE_CODE.sub(keep, CODE_FENCE.sub(keep, text)), slots


def restore(text: str, slots: list[str]) -> str:
    for i, s in enumerate(slots):
        text = text.replace(f"⟦{i}⟧", s)
    return text


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Split an oversized paragraph at whitespace, never inside a ⟦n⟧ code placeholder."""
    pieces = []
    while len(paragraph) > max_chars:
        cut = paragraph.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        opened = paragraph.rfind("⟦", 0, cut)
        if opened > paragraph.rfind("⟧", 0, cut):  # the cut would split a placeholder
            cut = opened if opened > 0 else paragraph.find("⟧", cut) + 1
        pieces.append(paragraph[:cut])
        paragraph = paragraph[cut:]
    return [*pieces, paragraph] if paragraph else pieces


def chunk(text: str, max_chars: int = 2500) -> list[str]:
    paras = re.split(r"(\n\s*\n)", text)
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > max_chars and cur.strip():
            out.append(cur)
            cur = ""
        if len(p) > max_chars:
            if cur:  # keep a pending separator in order (whitespace-only parts are passed through)
                out.append(cur)
                cur = ""
            out.extend(_split_long(p, max_chars))
            continue
        cur += p
    if cur.strip():
        out.append(cur)
    return out or [text]


def glossary_check(source: str, output: str, glossary: dict[str, str]) -> tuple[float, list[str]]:
    relevant = {k: v for k, v in glossary.items() if k.lower() in source.lower()}
    if not relevant:
        return 1.0, []
    missing = [k for k, v in relevant.items() if v.lower() not in output.lower()]
    return round(1 - len(missing) / len(relevant), 3), missing


class TranslationEngine:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self.glossaries = GlossaryStore(runtime.settings.data_dir / "glossaries.json",
                                        docs=getattr(runtime, "documents", None))

    def _model(self, preferred: str | None, private: bool = True):
        reg = self.rt.registry
        if preferred and preferred in reg.models:
            return reg.get(preferred)
        req = HydraRequest(messages=[Message(role="user", content="translate")], local_only=private)
        route = RoutingDecision(task_type=TaskType.CHAT, complexity=0.3, risk=0.1)
        ranked = reg.select(req, route)
        if not ranked:
            raise RuntimeError("no model available for translation")
        return ranked[0]

    async def _call(self, model, system: str, text: str) -> str:
        from hydra.core.budget import BudgetTracker, budget_for
        from hydra.core.context import TaskContext
        from hydra.scheduler.invoker import ModelInvoker

        req = HydraRequest(messages=[Message(role="user", content=text[:200])], mode=ExecutionMode.BALANCED)
        ctx = TaskContext(request=req, bus=self.rt.bus,
                          budget=BudgetTracker(budget_for(req, self.rt.settings.budget_time_scale)))
        invoker: ModelInvoker = self.rt.kernel.reasoner.invoker
        resp = await invoker.invoke(ctx, model, ModelRequest(messages=[
            {"role": "system", "content": system}, {"role": "user", "content": text}],
            temperature=0.1, max_tokens=max(256, int(len(text) * 1.6 / 3)), reasoning_level="off"),
            role="translator", hedge=False)
        return resp.content.strip()

    async def translate(self, req: TranslationRequest, private: bool = True) -> TranslationResult:
        t0 = time.perf_counter()
        glossary = {**(self.glossaries.get(req.glossary_name) if req.glossary_name else {}), **req.glossary}
        src = normalize_language(req.source_language) or detect_language(req.text)
        dst = normalize_language(req.target_language) or req.target_language
        model = self._model(req.model, private)
        gl = "\n".join(f"- {k} => {v}" for k, v in glossary.items()) or "(none)"
        system = SYSTEM.format(src=LANGUAGE_NAMES.get(src, src if src != "unknown" else "auto-detected language"),
                               dst=LANGUAGE_NAMES.get(dst, dst), domain=DOMAIN_HINT.get(req.domain, ""), glossary=gl)
        budget = RequestBudget(max_input_chars=self.rt.settings.max_input_chars,
                               max_chunks=self.rt.settings.max_translation_chunks)
        budget.validate_input(req.text)
        protected, slots = protect(req.text)
        parts = chunk(protected)
        budget.validate_chunks(sum(1 for part in parts if part.strip()))
        out = []
        for part in parts:
            if not part.strip():
                out.append(part)
                continue
            tr = await self._call(model, system, part)
            score, missing = glossary_check(part, tr, glossary)
            if missing:  # one corrective retry with the missing terms spelled out
                fix = system + "\nIMPORTANT: you MUST use: " + "; ".join(f"{k} => {glossary[k]}" for k in missing)
                tr2 = await self._call(model, fix, part)
                if glossary_check(part, tr2, glossary)[0] >= score:
                    tr = tr2
            lead = re.match(r"\s*", part).group(0)
            trail = part[len(part.rstrip()):]
            out.append(lead + tr.strip() + trail)
        translation = restore("".join(out), slots)
        comp, missing = glossary_check(req.text, translation, glossary)
        result = TranslationResult(source_language=src, target_language=dst, translation=translation, model=model.id,
                                   glossary_compliance=comp, missing_terms=missing, chunks=len(parts),
                                   latency_ms=round((time.perf_counter() - t0) * 1000, 1))
        corpus = getattr(self.rt, "corpus", None)
        if corpus is not None and translation:
            from hydra.corpus.records import CorpusRecord, RecordType, RightsMetadata

            rec, _ = corpus.ingest(CorpusRecord(
                record_type=RecordType.TRANSLATION, source_type="translation_engine", language=src,
                input={"prompt": f"Translate to {dst}: {req.text[:4000]}", "source_language": src,
                       "target_language": dst, "domain": req.domain},
                output={"translation": translation[:8000]}, quality=0.6 + 0.3 * comp, verification=comp,
                domain=["translation"], capabilities=[f"language.translate.{src}-{dst}"],
                rights=RightsMetadata(training_allowed=False), metadata={"glossary_terms": len(glossary)}))
            result.corpus_record = rec.id
        return result
