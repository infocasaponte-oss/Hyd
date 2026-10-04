# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hyd decision endpoints using HYDRA's authentication and rate limits."""
from __future__ import annotations

from typing import Any
from uuid import uuid4
import random
import time

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "hyd-latest"
    state: Any
    questions: dict[str, dict[str, Any]] = Field(min_length=1, max_length=64)


class PermutationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: DecisionBody
    question: str
    n_perm: int = Field(default=6, ge=1, le=64)
    seed: int = 0


def register(app, secured):
    @app.middleware("http")
    async def request_id(request, call_next):
        result = await call_next(request)
        if request.url.path.startswith(("/v1/systemone", "/v1/hyd")):
            result.headers.setdefault("x-typesafe-request-id", str(uuid4()))
        return result
    def controller(request):
        from hydra.hyd.controller import HydController
        observer = request.app.state.runtime.kernel.router.observer
        if not isinstance(observer, HydController):
            raise HTTPException(503, "Hyd is disabled")
        return observer

    async def invoke(hyd, state, questions, timeout=5):
        from hydra.hyd.controller import HydBusyError
        try:
            if timeout <= 0:
                raise TimeoutError()
            return await hyd.decide(state, questions, timeout_s=timeout)
        except TimeoutError:
            raise HTTPException(504, "Hyd decision deadline exceeded") from None
        except HydBusyError:
            raise HTTPException(429, "Hyd decision capacity is busy") from None
        except RuntimeError:
            raise HTTPException(503, "Hyd backend failed") from None
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise HTTPException(422, "invalid or oversized Hyd decision request") from None

    @app.get("/v1/hyd/status", dependencies=secured)
    async def status(request: Request):
        hyd = controller(request)
        return {"model": hyd.model, "model_revision": hyd.engine.ranker.revision,
                "backend": "hyd-native-contextual" if hasattr(hyd.engine.ranker, "backbone") else "hyd-native-cpu",
                "authority_enabled": hyd.authority.enabled,
                "trained_domain": hyd.engine.ranker.training.get("domain", "unknown"),
                "general_decision_quality": "unvalidated",
                "calibration_revision": hyd.calibration_revision,
                "limits": {"state_characters": 50000, "questions": 64, "options": 255}}

    @app.post("/v1/systemone", dependencies=secured)
    async def systemone(body: DecisionBody, request: Request, response: Response):
        hyd = controller(request)
        if body.model != hyd.model:
            raise HTTPException(422, "unknown Hyd model")
        result = await invoke(hyd, body.state, body.questions)
        response.headers["x-typesafe-request-id"] = str(uuid4())
        return result

    @app.post("/v1/systemone/permute", dependencies=secured)
    async def permute(body: PermutationBody, request: Request):
        hyd = controller(request)
        question = body.request.questions.get(body.question)
        if body.request.model != hyd.model or question is None or question.get("type") != "choice":
            raise HTTPException(422, "permutation requires a Hyd choice question")
        criteria = question.get("criteria")
        if not isinstance(criteria, dict) or not criteria:
            raise HTTPException(422, "invalid permutation criteria")
        try:
            hyd.engine.admit(body.request.state, body.request.questions)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise HTTPException(422, "invalid or oversized permutation request") from None
        rng, runs, started = random.Random(body.seed), [], time.perf_counter()
        for index in range(body.n_perm):
            order = list(criteria)
            if index:
                rng.shuffle(order)
            shuffled = {**question, "criteria": {key: criteria[key] for key in order}}
            result = await invoke(hyd, body.request.state, {body.question: shuffled}, 5 - (time.perf_counter() - started))
            answer = result["answers"][body.question]
            runs.append({"order": order, "probabilities": answer["probabilities"], "choice": answer["choice"]})
        return {"model": hyd.model, "model_revision": hyd.engine.ranker.revision,
                "runs": runs, "argmax_stable": len({row["choice"] for row in runs}) == 1,
                "spread": {key: max(row["probabilities"][key] for row in runs) - min(row["probabilities"][key] for row in runs) for key in criteria}}

    @app.post("/v1/systemone/separate", dependencies=secured)
    async def separate(body: DecisionBody, request: Request):
        hyd = controller(request)
        if body.model != hyd.model:
            raise HTTPException(422, "unknown Hyd model")
        try:
            hyd.engine.admit(body.state, body.questions)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise HTTPException(422, "invalid or oversized separate request") from None
        answers, tokens, started = {}, 0, time.perf_counter()
        for key, question in body.questions.items():
            result = await invoke(hyd, body.state, {key: question}, 5 - (time.perf_counter() - started))
            answers.update(result["answers"])
            tokens += result["usage"]["input_tokens"]
        return {"model": hyd.model, "model_revision": hyd.engine.ranker.revision,
                "answers": answers, "generation_tokens": 0, "usage": {"input_tokens": tokens, "output_tokens": 0}}
