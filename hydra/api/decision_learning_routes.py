# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Administrative human review of local learning rounds, independent of Lovable."""
import asyncio
import contextlib
import json
import sqlite3
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_rounds import RoundController
from hydra.router.decision_contract import CRITERIA


class LearningReview(BaseModel):
    case_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=50)
    reviewer: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)


def register(app, secured, root):
    def controller():
        return RoundController(root)

    @app.get("/hydra/v1/learning/review", response_class=HTMLResponse)
    async def page():
        from hydra.api.platform_routes import STUDIO_HEADERS
        return HTMLResponse(Path(__file__).with_name("learning_review.html").read_text(encoding="utf-8"), headers=STUDIO_HEADERS)

    @app.get("/hydra/v1/learning/rounds/{identity}", dependencies=secured)
    async def status(identity: str):
        try:
            state = controller().status(identity)
            queue = Path(root) / identity / "review"
            rows = read_rows(queue / "original.jsonl") if (queue / "original.jsonl").exists() else []
            reviews = {}
            if (queue / "reviews.sqlite3").exists():
                with contextlib.closing(sqlite3.connect(queue / "reviews.sqlite3")) as db:
                    reviews = {i: json.loads(p) for i, p in db.execute("SELECT id,payload FROM review_events ORDER BY seq")}
            return {"round": identity, "state": state["state"], "cases": rows,
                    "reviews": reviews, "labels": list(CRITERIA)}
        except ValueError:
            raise HTTPException(404, "unknown round") from None

    @app.post("/hydra/v1/learning/rounds/{identity}/review", dependencies=secured)
    async def review(identity: str, body: LearningReview):
        try:
            return await asyncio.to_thread(controller().review, identity, body.case_id, body.label, body.reviewer, body.notes)
        except (ValueError, RuntimeError):
            raise HTTPException(409, "review rejected: verify round, case, label and factory state") from None

    @app.post("/hydra/v1/learning/rounds/{identity}/tick", dependencies=secured)
    async def tick(identity: str):
        try:
            # The GPU worker trains; an HTTP request never starts a long training job.
            result = await asyncio.to_thread(controller().tick, identity, train=False)
            return {"round": identity, "state": result["state"], "result": result["result"]}
        except (ValueError, RuntimeError):
            raise HTTPException(409, "round failed validation or factory is busy; inspect local evidence") from None
