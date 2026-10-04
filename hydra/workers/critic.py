# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.core.events import EventType
from hydra.registry.models import ModelProfile
from hydra.workers.base import Worker

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "score", "issues"],
}


class CriticWorker(Worker):
    role = "critic"
    system_prompt = (
        "Revisa críticamente esta respuesta.\n"
        "Detecta:\n- errores\n- contradicciones\n- suposiciones débiles\n- hechos no demostrados\n"
        "Devuelve SOLO JSON: {\"verdict\": \"pass\"|\"fail\", \"score\": 0..1, \"issues\": [..]}. "
        "score = probabilidad de que la respuesta sea correcta y completa."
    )

    async def execute(self, ctx: TaskContext, model: ModelProfile, candidate: dict) -> dict:
        tool_lines = [
            f"{r.get('tool')}: {str(r.get('result'))[:1500]}" for r in ctx.state.tool_results[-5:]
        ]
        messages = [
            {"role": "system", "content": self.prompt_for(ctx)},
            {"role": "user", "content": (
                f"TAREA:\n{ctx.request.last_user_text[:6000]}\n\n"
                + ("RESULTADOS DE HERRAMIENTAS:\n" + "\n".join(tool_lines) + "\n\n" if tool_lines else "")
                + f"RESPUESTA:\n\n{candidate['answer'][:12000]}"
            )},
        ]
        resp = await self.invoker.invoke(
            ctx, model,
            ModelRequest(messages=messages, temperature=0, max_tokens=600, response_schema=CRITIC_SCHEMA),
            role=self.role, hedge=False,
        )
        data = resp.structured or {}
        critique = {
            "model": resp.model_id,
            "target": candidate.get("claim_id"),
            "verdict": data.get("verdict", "pass"),
            "score": float(data.get("score", 0.5)),
            "issues": list(data.get("issues", []))[:10],
        }
        await ctx.emit(EventType.CRITIQUE_ADDED, self.role, critique)
        passed = critique["verdict"] == "pass" and critique["score"] >= 0.5
        await self.add_evidence(ctx, candidate.get("claim_id", ""), "critic", resp.model_id,
                                critique["score"] if passed else 1 - critique["score"], passed)
        return critique
