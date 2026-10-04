# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Perception layer: the VLM does not just "describe images"; it updates the world state."""

from __future__ import annotations

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.registry.models import ModelProfile
from hydra.workers.base import Worker

PERCEPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "objects": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "type": {"type": "string"},
            "attributes": {"type": "object"}, "confidence": {"type": "number"}}, "required": ["name"]}},
        "relations": {"type": "array", "items": {"type": "object", "properties": {
            "subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"}},
            "required": ["subject", "predicate", "object"]}},
        "text": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["description", "objects"],
}


class PerceptionWorker(Worker):
    role = "vision"
    system_prompt = (
        "You are HYDRA's perception layer. Look at the image(s) and return ONLY JSON describing "
        "the scene structurally: a one-sentence description, the objects (with attributes such as "
        "color, position, state, UI role), spatial/logical relations between objects, and any "
        "visible text (OCR). Be literal; do not guess what is not visible."
    )

    async def execute(self, ctx: TaskContext, model: ModelProfile) -> dict:
        images = ctx.request.images
        resp = await self.invoker.invoke(
            ctx, model,
            ModelRequest(messages=[
                {"role": "system", "content": self.prompt_for(ctx)},
                {"role": "user", "content": f"Context from the user: {ctx.request.last_user_text[:2000]}",
                 "images": images},
            ], temperature=0, max_tokens=1500, response_schema=PERCEPTION_SCHEMA),
            role=self.role, hedge=False,
        )
        observation = resp.structured or {"description": resp.content, "objects": []}
        observation["model"] = resp.model_id
        return observation
