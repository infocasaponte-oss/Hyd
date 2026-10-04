# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Artifact Engine: HYDRA's output is typed artifacts, not only text, so components can
manipulate results without round-tripping through natural language."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

FENCE = re.compile(r"```([\w+.-]*)[ \t]*\n(.*?)```", re.S)


class ArtifactType(str, Enum):
    ANSWER = "answer"
    CODE = "code"
    CODE_PATCH = "code_patch"
    REPORT = "report"
    DATASET = "dataset"
    IMAGE = "image"
    EXECUTION_PLAN = "execution_plan"
    MODEL = "model"
    RESEARCH_GRAPH = "research_graph"


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: f"art-{uuid.uuid4().hex[:10]}")
    type: ArtifactType
    title: str
    mime: str
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)  # claim ids / event refs


def _is_patch(lang: str, body: str) -> bool:
    return lang in ("diff", "patch") or bool(re.search(r"^--- a/.*\n\+\+\+ b/", body, re.M))


def _dataset(lang: str, body: str) -> Any | None:
    if lang == "json":
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
            return data
        return None
    if lang in ("csv", "tsv"):
        rows = list(csv.DictReader(io.StringIO(body), delimiter="\t" if lang == "tsv" else ","))
        return rows or None
    return None


class ArtifactEngine:
    def extract(
        self,
        answer: str,
        *,
        plan: dict | None = None,
        research_graph: dict | None = None,
        images: list[str] | None = None,
        claims: list[dict] | None = None,
        task_type: str = "chat",
    ) -> list[Artifact]:
        arts = [Artifact(type=ArtifactType.ANSWER, title="Answer", mime="text/markdown", content=answer,
                         provenance=[c["id"] for c in (claims or [])])]
        for i, m in enumerate(FENCE.finditer(answer)):
            lang, body = m.group(1).lower(), m.group(2)
            if _is_patch(lang, body):
                files = re.findall(r"^\+\+\+ b/(\S+)", body, re.M)
                arts.append(Artifact(type=ArtifactType.CODE_PATCH, title=f"Patch {i + 1}", mime="text/x-diff",
                                     content=body, metadata={"files": files}))
            elif (rows := _dataset(lang, body)) is not None:
                arts.append(Artifact(type=ArtifactType.DATASET, title=f"Dataset {i + 1}",
                                     mime="application/json", content=rows,
                                     metadata={"rows": len(rows), "columns": sorted(rows[0].keys())}))
            else:
                arts.append(Artifact(type=ArtifactType.CODE, title=f"Code {i + 1} ({lang or 'text'})",
                                     mime="text/plain", content=body, metadata={"language": lang or "text"}))
        if plan:
            arts.append(Artifact(type=ArtifactType.EXECUTION_PLAN, title=f"Plan: {plan.get('strategy')}",
                                 mime="application/json", content=plan))
        if research_graph:
            arts.append(Artifact(type=ArtifactType.RESEARCH_GRAPH, title="Research graph",
                                 mime="application/json", content=research_graph))
            if task_type == "research":
                arts.append(Artifact(type=ArtifactType.REPORT, title="Research report", mime="text/markdown",
                                     content=answer, metadata={"subquestions": len(research_graph.get("nodes", []))}))
        for i, img in enumerate(images or []):
            mime = img.split(";")[0][5:] if img.startswith("data:") else "image/*"
            arts.append(Artifact(type=ArtifactType.IMAGE, title=f"Input image {i + 1}", mime=mime,
                                 content=img if len(img) < 200_000 else img[:64] + "…",
                                 metadata={"role": "input"}))
        return arts
