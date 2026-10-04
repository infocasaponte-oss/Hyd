# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Research Graph: investigate large problems hierarchically instead of one giant prompt chain.

Question
 ├─ subquestion A ── source 1, source 2
 ├─ subquestion B ── experiment
 └─ subquestion C ── contradiction ── verification
"""

from __future__ import annotations

import re
from itertools import combinations

from pydantic import BaseModel, Field

from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest
from hydra.core.events import EventType
from hydra.registry.models import ModelProfile
from hydra.scheduler.parallel import run_parallel
from hydra.verification.consensus import pair_agreement
from hydra.verification.uncertainty import NUM, content_tokens
from hydra.workers.base import Worker

DECOMPOSE_SCHEMA = {
    "type": "object",
    "properties": {"subquestions": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["subquestions"],
}


class RNode(BaseModel):
    id: str
    kind: str  # question | subquestion | source | experiment | contradiction | verification | answer
    text: str
    data: dict = Field(default_factory=dict)


class REdge(BaseModel):
    source: str
    target: str
    relation: str


class ResearchGraph(BaseModel):
    nodes: list[RNode] = Field(default_factory=list)
    edges: list[REdge] = Field(default_factory=list)

    def add(self, kind: str, text: str, parent: str | None = None, relation: str = "has", **data) -> str:
        nid = f"{kind[:3]}{len(self.nodes) + 1}"
        self.nodes.append(RNode(id=nid, kind=kind, text=text[:2000], data=data))
        if parent:
            self.edges.append(REdge(source=parent, target=nid, relation=relation))
        return nid

    def of_kind(self, kind: str) -> list[RNode]:
        return [n for n in self.nodes if n.kind == kind]


def heuristic_split(question: str, max_parts: int = 4) -> list[str]:
    parts = [p.strip(" ,;") for p in re.split(r"\?\s+|;\s+|\n+|\s+(?:y además|and also|además)\s+", question)
             if len(p.strip()) > 12]
    return parts[:max_parts] if len(parts) > 1 else [question]


def contradicts(a: str, b: str) -> bool:
    """Same topic, different numbers -> likely contradiction."""
    shared = content_tokens(a) & content_tokens(b)
    na, nb = set(NUM.findall(a)), set(NUM.findall(b))
    return len(shared) >= 3 and bool(na) and bool(nb) and not (na & nb)


class ResearchWorker(Worker):
    role = "researcher"
    system_prompt = (
        "You are HYDRA's research planner. Decompose the question into at most 5 independent, "
        "concrete sub-questions whose answers together answer the question. Return ONLY JSON."
    )

    def __init__(self, invoker, answerer: Worker, **kw) -> None:
        super().__init__(invoker, **kw)
        self.answerer = answerer

    async def decompose(self, ctx: TaskContext, model: ModelProfile) -> list[str]:
        try:
            resp = await self.invoker.invoke(
                ctx, model,
                ModelRequest(messages=[
                    {"role": "system", "content": self.prompt_for(ctx)},
                    {"role": "user", "content": ctx.request.last_user_text[:6000]},
                ], temperature=0, max_tokens=600, response_schema=DECOMPOSE_SCHEMA),
                role=self.role, hedge=False,
            )
            subs = [s for s in (resp.structured or {}).get("subquestions", []) if isinstance(s, str) and s.strip()]
        except Exception:
            subs = []
        return subs[:5] or heuristic_split(ctx.request.last_user_text)

    async def execute(self, ctx: TaskContext, planner_model: ModelProfile, models: list[ModelProfile]
                      ) -> tuple[ResearchGraph, list[dict]]:
        graph = ResearchGraph()
        root = graph.add("question", ctx.request.last_user_text)
        subs = await self.decompose(ctx, planner_model)
        sub_ids = [graph.add("subquestion", s, root, "decomposes_into") for s in subs]

        async def answer(i: int, sub: str):
            model = models[i % len(models)]
            tools_before = len(ctx.state.tool_results)
            cand = await self.answerer.execute(ctx, model, index=100 + i,
                                               messages=[{"role": "user", "content": sub}])
            return cand, ctx.state.tool_results[tools_before:]

        results = await run_parallel([lambda i=i, s=s: answer(i, s) for i, s in enumerate(subs)])
        answers: list[tuple[str, dict]] = []
        for sid, res in zip(sub_ids, results):
            if isinstance(res, BaseException):
                graph.add("verification", f"failed: {res}", sid, "failed")
                continue
            cand, tools = res
            aid = graph.add("answer", cand["answer"], sid, "answered_by", model=cand["model"])
            for t in tools:
                kind = "experiment" if t.get("tool") == "python.execute" else "source"
                graph.add(kind, f"{t.get('tool')}: {str(t.get('result'))[:500]}", aid, "supported_by")
            answers.append((aid, cand))

        for (ida, a), (idb, b) in combinations(answers, 2):
            if contradicts(a["answer"], b["answer"]):
                cid = graph.add("contradiction", f"{ida} vs {idb}", ida, "contradicts", other=idb)
                graph.edges.append(REdge(source=idb, target=cid, relation="contradicts"))

        await ctx.emit(EventType.RESEARCH_GRAPH_UPDATED, self.role, graph.model_dump())
        return graph, [c for _, c in answers]

    @staticmethod
    def merge(question: str, graph: ResearchGraph, answers: list[dict]) -> str:
        """Deterministic report used as the research candidate (the synthesizer may polish it)."""
        subs = {e.target: n.text for n in graph.of_kind("subquestion")
                for e in graph.edges if e.source == n.id and e.relation == "answered_by"}
        lines = []
        by_id = {n.id: n for n in graph.nodes}
        for aid, sub in subs.items():
            lines.append(f"**{sub}**\n{by_id[aid].text}")
        for c in graph.of_kind("contradiction"):
            lines.append(f"⚠️ Contradicción detectada entre sub-respuestas: {c.text}")
        return "\n\n".join(lines) if lines else "\n\n".join(a["answer"] for a in answers)

    @staticmethod
    def consistency(answers: list[dict]) -> float | None:
        if len(answers) < 2:
            return None
        pairs = list(combinations([a["answer"] for a in answers], 2))
        return sum(pair_agreement(a, b) for a, b in pairs) / len(pairs)
