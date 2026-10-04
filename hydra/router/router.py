# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hybrid cognitive router: RULES -> FAST CLASSIFIER -> POLICY ENGINE.

The router never answers. A generative classifier may refine rule-based signals.
An optional typed decision observer collects experimental evidence only.
"""

from __future__ import annotations

import json
import logging
import re

from hydra.core.contracts import (
    DecisionObservation,
    ExecutionMode,
    HydraRequest,
    ModelRequest,
    RoutingDecision,
    TaskType,
)
from hydra.router.observer import DecisionObserver
from hydra.router.scoring import SOURCE_SIGNAL
from hydra.verification.grounding import has_source
from hydra.router.decision_authority import DecisionAuthority

log = logging.getLogger("hydra.router")

KEYWORDS: dict[TaskType, tuple[str, ...]] = {
    TaskType.CODING: (
        "python", "rust", "javascript", "typescript", "java", "golang", "c++", "sql",
        "código", "codigo", "code", "bug", "función", "funcion", "function", "script",
        "compila", "compile", "stack trace", "traceback", "exception", "refactor",
        "def ", "class ", "import ", "```",
    ),
    TaskType.REASONING: (
        "demuestra", "demostrar", "prove", "razona", "reason", "matemática", "matematica",
        "math", "analiza", "analyze", "analyse", "calcula", "calculate", "ecuación",
        "equation", "lógica", "logica", "logic", "por qué", "why", "teorema", "theorem",
        "probabilidad", "probability", "optimiza", "optimize", "plan",
    ),
    TaskType.RESEARCH: (
        "investiga", "research", "busca", "search", "fuentes", "sources", "compara",
        "compare", "estado del arte", "state of the art", "documentación", "papers",
        "resumen de", "summarize",
    ),
    TaskType.VISION: (
        "imagen", "image", "foto", "photo", "captura", "screenshot", "diagrama",
        "diagram", "vídeo", "video", "ocr", "píxel", "pixel",
    ),
    TaskType.TOOL_USE: (
        "ejecuta", "execute", "run ", "lee el archivo", "read the file", "escribe el archivo",
        "write the file", "descarga", "download", "fetch", "consulta la base", "query the database",
        "git diff", "aplica el parche", "apply the patch",
    ),
}

HIGH_RISK = (
    "producción", "production", "borra", "delete", "drop table", "rm -rf", "dinero",
    "money", "pago", "payment", "médico", "medical", "legal", "seguridad", "security",
    "contraseña", "password",
)

ROUTER_PROMPT = (
    "You are HYDRA's routing classifier. Do NOT answer the user. Return JSON only with "
    'keys: "task_type" (chat|coding|reasoning|research|vision|tool_use), "complexity" '
    '(0..1), "risk" (0..1), "requires_tools", "requires_vision", "requires_reasoning", '
    '"requires_verification", "requires_memory" (booleans).'
)

ROUTING_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {"type": "string", "enum": [t.value for t in TaskType]},
        "complexity": {"type": "number"},
        "risk": {"type": "number"},
        "requires_tools": {"type": "boolean"},
        "requires_vision": {"type": "boolean"},
        "requires_reasoning": {"type": "boolean"},
        "requires_verification": {"type": "boolean"},
        "requires_memory": {"type": "boolean"},
    },
    "required": ["task_type", "complexity", "risk"],
}


def _hits(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in text)


class CognitiveRouter:
    def route_native(self, task):
        """Route the published native contract without applying request-schema defaults."""
        from hydra.router.native import CapabilityRouter

        return CapabilityRouter().route(task)

    def __init__(self, classifier=None, classifier_model: str | None = None,
                 *, observer: DecisionObserver | None = None,
                 authority: DecisionAuthority | None = None) -> None:
        """Keep the generative classifier separate from typed shadow observations."""
        self.classifier = classifier
        self.classifier_model = classifier_model
        self.observer = observer
        self.authority = authority

    async def route(self, request: HydraRequest) -> RoutingDecision:
        decision = self._rules(request)
        if self.classifier is not None and request.mode != ExecutionMode.FAST:
            decision = await self._refine(request, decision)
        decision = self._policy(request, decision)
        if self.observer is not None:
            try:
                decision.observation = await self.observer.observe(request)
            except Exception:
                # An advisory backend must not break policy routing. Cancellation
                # still propagates (CancelledError is a BaseException).
                log.warning("decision observer failed; preserving policy routing")
                decision.observation = DecisionObservation(status="error",
                    model=getattr(self.observer, "model", "unknown"), reason="observer.failure")
                return decision
            hint = self.authority.task_hint(decision.observation) if self.authority else None
            if (hint is not None and decision.risk < .5 and not request.images
                    and hint != TaskType.VISION and not (decision.observation.reason or "").startswith("policy_gate")):
                decision.task_type = hint
                decision.requires_reasoning = decision.requires_reasoning or hint == TaskType.REASONING
                decision.requires_tools = decision.requires_tools or hint == TaskType.CODING
                decision.signals["decision.controlled_hint"] = 1
                decision = self._policy(request, decision)
        return decision

    async def close(self) -> None:
        if self.observer is not None:
            await self.observer.close()

    # ---- layer 1: deterministic rules -------------------------------------------------
    def _rules(self, request: HydraRequest) -> RoutingDecision:
        text = request.text.lower()
        hits = {t: _hits(text, words) for t, words in KEYWORDS.items()}
        has_image = bool(request.images) or bool(re.search(r"\.(png|jpe?g|gif|webp)\b", text))
        if has_image:
            hits[TaskType.VISION] += 3

        best = max(hits, key=lambda t: hits[t])
        task = best if hits[best] > 0 else TaskType.CHAT

        complexity = self._estimate_complexity(request, hits)
        risk = min(1.0, 0.1 + 0.25 * _hits(text, HIGH_RISK))

        signals = {f"kw.{t.value}": float(n) for t, n in hits.items()}
        # Only the latest message: a source pasted turns ago must not pin the whole chat to a specialist.
        if has_source(request.last_user_text):
            signals[SOURCE_SIGNAL] = 1.0
        return RoutingDecision(
            task_type=task,
            complexity=complexity,
            risk=risk,
            requires_tools=task in (TaskType.CODING, TaskType.TOOL_USE) or hits[TaskType.TOOL_USE] > 0,
            requires_vision=task == TaskType.VISION or has_image,
            requires_reasoning=complexity > 0.55 or task == TaskType.REASONING,
            requires_verification=complexity > 0.7 or risk > 0.5,
            requires_memory=bool(re.search(r"\b(recuerda|remember|antes|previous|last time|como siempre)\b", text)),
            desired_parallelism=3 if complexity > 0.8 else 1,
            signals=signals,
        )

    @staticmethod
    def _estimate_complexity(request: HydraRequest, hits: dict[TaskType, int]) -> float:
        chars = sum(len(m.content) for m in request.messages)
        base = 0.15 + chars / 10_000
        base += 0.05 * min(sum(hits.values()), 6)
        base += 0.05 * request.text.count("\n") / 20
        if hits[TaskType.REASONING] >= 2:
            base += 0.15
        return round(min(1.0, base), 3)

    # ---- layer 2: fast learned classifier ----------------------------------------------
    async def _refine(self, request: HydraRequest, rules: RoutingDecision) -> RoutingDecision:
        try:
            result = await self.classifier.generate(
                self.classifier_model,
                ModelRequest(
                    messages=[
                        {"role": "system", "content": ROUTER_PROMPT},
                        {"role": "user", "content": request.last_user_text[:4000]},
                    ],
                    temperature=0,
                    max_tokens=200,
                    response_schema=ROUTING_SCHEMA,
                    timeout_s=5,
                ),
            )
            data = result.structured or json.loads(result.content)
            llm = RoutingDecision.model_validate({**data, "desired_parallelism": 1})
        except Exception as exc:  # classifier is advisory only
            log.debug("classifier failed, using rules: %s", exc)
            return rules

        # Blend: rules win on hard signals, the classifier sharpens soft ones.
        task = llm.task_type if rules.signals.get(f"kw.{rules.task_type.value}", 0) < 2 else rules.task_type
        complexity = round((rules.complexity + llm.complexity) / 2, 3)
        return rules.model_copy(update={
            "task_type": task,
            "complexity": complexity,
            "risk": max(rules.risk, llm.risk),
            "requires_tools": rules.requires_tools or llm.requires_tools,
            "requires_vision": rules.requires_vision or llm.requires_vision,
            "requires_reasoning": rules.requires_reasoning or llm.requires_reasoning,
            "requires_verification": rules.requires_verification or llm.requires_verification,
            "requires_memory": rules.requires_memory or llm.requires_memory,
            "signals": {**rules.signals, "classifier": 1.0},
        })

    # ---- layer 3: policy engine ----------------------------------------------------------
    @staticmethod
    def _policy(request: HydraRequest, d: RoutingDecision) -> RoutingDecision:
        update: dict = {}
        match request.mode:
            case ExecutionMode.FAST:
                update = {"desired_parallelism": 1, "requires_verification": False}
            case ExecutionMode.DEEP:
                update = {
                    "desired_parallelism": max(d.desired_parallelism, 3),
                    "requires_verification": True,
                    "requires_reasoning": True,
                    "complexity": max(d.complexity, 0.6),
                }
            case ExecutionMode.MAX:
                update = {
                    "desired_parallelism": 5,
                    "requires_verification": True,
                    "requires_reasoning": True,
                    "complexity": max(d.complexity, 0.85),
                }
        if d.risk > 0.9:
            update["desired_parallelism"] = max(update.get("desired_parallelism", d.desired_parallelism), 3)
            update["requires_verification"] = True
        return d.model_copy(update=update) if update else d
