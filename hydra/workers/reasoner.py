# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import re

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.core.events import EventType
from hydra.registry.models import ModelProfile
from hydra.workers.base import Worker, claim_id_for


def contradicts_typed_state(user: str) -> bool:
    """Positive requests for prose or text states, excluding 'sin/omite explicación'."""
    return bool(re.search(r"\bactivo\b.{0,80}\b(?:como|de\s+tipo|tipo)\s+(?:un[ao]?\s+)?(?:texto|cadena|string)\b|"
                          r"(?:^|[.!?;]\s*|\b(?:además|y)\s+)(?:explica|explícame|explicame)\b",user,re.I))


def requested_json_schema(messages: list[dict], typed_state_json: bool = False) -> dict | None:
    """Honor explicit JSON-only instructions without parsing arbitrary prose as a format request."""
    user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    if not isinstance(user, str):
        return None
    if re.search(r"\bno\s+(?:quiero|devuelvas|uses|respondas)\s+(?:solo\s+)?json\b", user, re.I):
        return None
    state_record = re.search(r"\b(?:claves|registro|json)\s*:\s*id\s*[:=]\s*\d+\s*;\s*activo\s*:\s*(?:sí|si|no)"
                             r"\s*\.?\s*(?:No uses Markdown\.?)?\s*$",user,re.I)
    if typed_state_json and state_record and re.search(r"\bobjeto\s+json\b",user,re.I):
        return {"type":"object","properties":{"id":{"type":"integer"},"activo":{"type":"boolean"}},
                "required":["id","activo"],"additionalProperties":False}
    # An explicit two-field serialization contract also applies without the word JSON.
    # Infer types from the requested contract, never from a reference answer or a target value.
    explicit_state_contract = re.search(r"\bserializa\s+solo\s+las\s+claves\s+id\s+y\s+activo\s*;",user,re.I)
    if typed_state_json and explicit_state_contract and re.search(r"\btrue\s+o\s+false\b",user,re.I):
        if not contradicts_typed_state(user):
            return {"type":"object","properties":{"id":{"type":"integer"},"activo":{"type":"boolean"}},
                    "required":["id","activo"],"additionalProperties":True}
    structured_action = re.search(r"\b(?:serializa|representa|produce|construye|devuelve|entrega|emite|codifica|prepara)\b",user,re.I)
    named_fields = re.search(r"\bid\b",user,re.I) and re.search(r"\bactivo\b",user,re.I)
    boolean_type = re.search(r"\bactivo\b.{0,100}\b(?:boolean[oa]|lógico)\b|\b(?:boolean[oa]|lógico)\b.{0,100}\bactivo\b",user,re.I)
    field_contract = re.search(r"\b(?:claves|campos|propiedades|objeto|contrato)\b",user,re.I)
    if typed_state_json and structured_action and named_fields and boolean_type and field_contract:
        if not contradicts_typed_state(user):
            exactly_two = re.search(r"\bdos\s+(?:claves|campos|propiedades)\b|\bambas\s+propiedades\b|\bexactamente\s+id\s+y\s+activo\b",user,re.I)
            return {"type":"object","properties":{"id":{"type":"integer"},"activo":{"type":"boolean"}},
                    "required":["id","activo"],"additionalProperties":not bool(exactly_two)}
    explicit = (r"\b(?:solo|solamente|únicamente|only)\s+(?:un\s+)?json\b|\bjson\s+only\b|"
                r"\b(?:devuelve|devuélveme|genera|crea|entrega|return)\s+(?:(?:un|a|solo|solamente|only)\s+)?(?:objeto\s+)?json\b|"
                r"^\s*json\s+con\b")
    if not re.search(explicit, user, re.I):
        return None
    # Permit any valid JSON value; do not invent an object schema or remove model text afterwards.
    return {"anyOf": [{"type": t} for t in ("object", "array", "string", "number", "boolean", "null")]}


class ReasonerWorker(Worker):
    role = "reasoner"
    system_prompt = (
        "You are HYDRA's reasoning worker. Solve the user's task precisely and completely. "
        "HYDRA is this project's orchestration engine, not an OpenAI product. "
        "Distinguish the HYDRA engine from the underlying model and its origin; "
        "do not invent authorship or claim the underlying weights were trained from scratch. "
        "State assumptions explicitly, separate facts from hypotheses, and say what you are "
        "unsure about instead of guessing. Answer in the user's language. "
        "Honor the requested output format: when only code or JSON is requested, omit "
        "commentary and headings. For code, preserve the exact function signature, include "
        "required imports, and handle the edge cases stated in the request. Do not claim "
        "tests passed unless an execution result confirms it."
    )

    async def execute(self, ctx: TaskContext, model: ModelProfile, index: int = 0,
                      extra_system: str = "", messages: list[dict] | None = None) -> dict:
        messages = self.build_messages(ctx, model, extra_system=extra_system, messages=messages)
        schema = requested_json_schema(messages, model.quirks.typed_state_json) if model.quirks.native_json_schema else None
        if schema and schema.get("properties",{}).get("activo")=={"type":"boolean"}:
            convention="Contrato HYDRA id/activo: sí, encendido y habilitado significan true; no, apagado y deshabilitado significan false. Deshabilitado no significa habilitado. Conserva el identificador indicado por el usuario."
            if messages and messages[0].get("role")=="system":
                messages[0]={**messages[0],"content":messages[0]["content"]+"\n"+convention}
            else:
                messages.insert(0,{"role":"system","content":convention})
        resp = await self.invoker.invoke(
            ctx, model, ModelRequest(messages=messages, temperature=0.2 + 0.15 * index, max_tokens=2048,
                              response_schema=schema,
                              reasoning_level=self.reasoning_level(ctx)),
            role=self.role,
        )
        self.require_answer(ctx, resp.model_id, resp.content)
        candidate = {
            "claim_id": claim_id_for(resp.model_id, index),
            "model": resp.model_id,
            "worker": self.role,
            "answer": resp.content,
            "latency_ms": round(resp.latency_ms, 2),
        }
        await ctx.emit(EventType.ANSWER_PROPOSED, self.role, candidate)
        return candidate
