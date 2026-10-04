# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Synthesis from the belief state, not from the raw output of the first model."""

from __future__ import annotations

from pydantic import BaseModel, Field

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.registry.models import ModelProfile
from hydra.workers.base import Worker


class SynthesisInput(BaseModel):
    objective: str
    verified_facts: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class SynthesizerWorker(Worker):
    role = "synthesizer"
    system_prompt = (
        "You are HYDRA's synthesizer. Write the final answer for the user from the verified "
        "material below. Be clear and concise, keep code and numbers exact, do not add claims "
        "that are not supported by the material, and mention remaining uncertainty briefly "
        "only if it matters. Answer in the user's language."
    )

    @staticmethod
    def render(inp: SynthesisInput) -> str:
        parts = [f"OBJECTIVE:\n{inp.objective}"]
        if inp.verified_facts:
            parts.append("VERIFIED FACTS:\n" + "\n".join(f"- {f}" for f in inp.verified_facts))
        if inp.artifacts:
            parts.append("ARTIFACTS:\n" + "\n".join(inp.artifacts))
        parts.append("CONCLUSIONS:\n" + "\n".join(f"- {c}" for c in inp.conclusions))
        if inp.uncertainties:
            parts.append("UNCERTAINTIES:\n" + "\n".join(f"- {u}" for u in inp.uncertainties))
        return "\n\n".join(parts)

    async def execute(self, ctx: TaskContext, model: ModelProfile | None, inp: SynthesisInput,
                      use_model: bool) -> str:
        """Without a model call, the best conclusion is returned as-is (no extra cost)."""
        if not use_model or model is None or not ctx.budget.can_call_model():
            return inp.conclusions[0] if inp.conclusions else ""
        resp = await self.invoker.invoke(
            ctx, model,
            ModelRequest(messages=[
                {"role": "system", "content": self.prompt_for(ctx)},
                {"role": "user", "content": self.render(inp)},
            ], temperature=0.2, max_tokens=2048),
            role=self.role, hedge=False,
        )
        return resp.content or (inp.conclusions[0] if inp.conclusions else "")
