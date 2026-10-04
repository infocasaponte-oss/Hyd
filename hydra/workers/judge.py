# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Judge: compare candidates -> common facts -> disagreements -> select/merge strongest evidence.
Never just 'which answer do you like more?'."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.core.events import EventType
from hydra.registry.models import ModelProfile
from hydra.verification.consensus import agreement, support_for
from hydra.workers.base import Worker

log = logging.getLogger("hydra.judge")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "best_index": {"type": "integer", "minimum": 0},
        "agreement": {"type": "number", "minimum": 0, "maximum": 1},
        "common_facts": {"type": "array", "items": {"type": "string"}},
        "disagreements": {"type": "array", "items": {"type": "string"}},
        "merged_answer": {"type": ["string", "null"]},
    },
    "required": ["best_index", "agreement", "common_facts", "disagreements"],
}


class JudgeResult(BaseModel):
    best_index: int
    agreement: float | None
    common_facts: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    merged_answer: str | None = None
    method: str = "model"


class JudgeWorker(Worker):
    role = "judge"
    system_prompt = (
        "You are HYDRA's judge. Compare the candidate answers using concrete criteria: "
        "correctness, evidence (tool results), internal consistency, completeness, and "
        "agreement with the other candidates. 1) Extract facts common to the candidates. "
        "2) Identify disagreements. 3) Select the candidate with the strongest evidence, or "
        "merge them if a combination is strictly better. Return ONLY JSON."
    )

    @staticmethod
    def consensus(candidates: list[dict]) -> JudgeResult:
        answers = [c["answer"] for c in candidates]
        support = [support_for(i, answers) for i in range(len(answers))]
        evidence_bonus = [len(c.get("tools_used", [])) for c in candidates]
        best = max(range(len(candidates)), key=lambda i: (support[i], evidence_bonus[i], -i))
        return JudgeResult(best_index=best, agreement=agreement(answers), method="consensus")

    async def execute(self, ctx: TaskContext, model: ModelProfile, candidates: list[dict]) -> JudgeResult:
        fallback = self.consensus(candidates)
        if len(candidates) < 2 or not ctx.budget.can_call_model():
            return fallback
        blocks = "\n\n".join(
            f"### CANDIDATE {i} (model={c['model']}, tools={c.get('tools_used', [])})\n{c['answer'][:6000]}"
            for i, c in enumerate(candidates)
        )
        messages = [
            {"role": "system", "content": self.prompt_for(ctx)},
            {"role": "user", "content": f"TASK:\n{ctx.request.last_user_text[:4000]}\n\n{blocks}"},
        ]
        try:
            resp = await self.invoker.invoke(
                ctx, model,
                ModelRequest(messages=messages, temperature=0, max_tokens=1500, response_schema=JUDGE_SCHEMA),
                role=self.role, hedge=False,
            )
            data = resp.structured or {}
            result = JudgeResult(
                best_index=min(max(int(data.get("best_index", fallback.best_index)), 0), len(candidates) - 1),
                agreement=fallback.agreement if fallback.agreement is not None else data.get("agreement"),
                common_facts=[str(x) for x in data.get("common_facts", [])][:20],
                disagreements=[str(x) for x in data.get("disagreements", [])][:20],
                merged_answer=data.get("merged_answer") or None,
            )
        except Exception as exc:
            log.warning("judge failed, using consensus: %s", exc)
            result = fallback

        for fact in result.common_facts:
            await ctx.emit(EventType.FACT_ADDED, self.role, {"fact": fact, "source": "judge"})
        for dis in result.disagreements:
            await ctx.emit(EventType.HYPOTHESIS_ADDED, self.role, {"claim": dis, "status": "disputed"})
        return result
