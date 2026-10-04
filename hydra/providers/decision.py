# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Local typed decision API, separate from generative providers and tool authorization."""
from __future__ import annotations

import math
from typing import Protocol
from urllib.parse import urlparse

import httpx


def canonicalize_questions(questions: dict) -> tuple[dict, dict[str, list[str]]]:
    """Sort choice labels sent to the model and remember each caller's order."""
    canonical: dict = {}
    orders: dict[str, list[str]] = {}
    for key, question in questions.items():
        copied = dict(question)
        if question.get("type") == "choice":
            labels = list(question["criteria"])
            orders[key] = labels
            copied["criteria"] = {label: question["criteria"][label] for label in sorted(labels)}
        canonical[key] = copied
    return canonical, orders


def restore_choice_order(payload: dict, orders: dict[str, list[str]]) -> dict:
    """Remap probability dictionaries to the exact order supplied by the caller."""
    result = dict(payload)
    answers = {key: dict(value) for key, value in payload.get("answers", {}).items()}
    for key, labels in orders.items():
        if key in answers and "probabilities" in answers[key]:
            answers[key]["probabilities"] = {label: answers[key]["probabilities"][label] for label in labels}
    result["answers"] = answers
    return result


def probability(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


def validate_questions(questions: dict) -> None:
    if not questions:
        raise ValueError("questions must not be empty")
    for q in questions.values():
        kind = q.get("type")
        criteria = q.get("criteria")
        if kind == "noul":
            if criteria is not None and (not isinstance(criteria, dict) or not set(criteria) <= {"true", "false"}):
                raise ValueError("invalid noul criteria")
        elif kind == "choice":
            if not isinstance(criteria, dict) or not 1 <= len(criteria) <= 255:
                raise ValueError("choice requires 1..255 options")
        elif kind == "score":
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 255:
                raise ValueError("score requires 1..255 ordered levels")
        else:
            raise ValueError("unknown question type")


def validate_answers(questions: dict, payload: dict) -> dict:
    answers = payload.get("answers", {})
    if set(answers) != set(questions):
        raise ValueError("answer IDs do not match questions")
    for key, question in questions.items():
        answer = answers[key]
        kind = question["type"]
        if answer.get("type") != kind:
            raise ValueError("answer type mismatch")
        if kind == "noul":
            probability(answer.get("noul"))
            continue
        expected = set(question["criteria"]) if kind == "choice" else {
            str(i) for i in range(len(question["criteria"]))}
        probs = answer.get("probabilities", {})
        if set(probs) != expected:
            raise ValueError("probability options mismatch")
        if abs(sum(probability(p) for p in probs.values()) - 1) > 0.001:
            raise ValueError("probabilities must sum to one")
        probability(answer.get("confidence"))
        if kind == "choice":
            selected = answer.get("choice")
            if selected not in expected or probs[selected] < max(probs.values()) - 0.001:
                raise ValueError("invalid selected option")
        else:
            score = answer.get("score")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("invalid score")
            mean = sum(int(i) * p for i, p in probs.items())
            if not 0 <= score <= len(expected) - 1 or abs(score - mean) > 0.01:
                raise ValueError("score does not match distribution")
    return payload


class DecisionProvider(Protocol):
    async def decide(self, state: str | dict | list, questions: dict) -> dict: ...


class LocalSystemOneProvider:
    """Kev-compatible backend. Returns evidence only; never grants action permissions."""

    def __init__(self, endpoint: str = "http://127.0.0.1:8009", model: str = "kev-latest",
                 api_key: str = "local", timeout: float = 5, transport=None):
        url = urlparse(endpoint)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("decision endpoint must be a local HTTP origin")
        self.model = model
        self.client = httpx.AsyncClient(base_url=endpoint.rstrip("/"), timeout=timeout,
                                       headers={"Authorization": f"Bearer {api_key}"},
                                       transport=transport, trust_env=False, follow_redirects=False)

    async def decide(self, state: str | dict | list, questions: dict) -> dict:
        validate_questions(questions)
        wire_questions, orders = canonicalize_questions(questions)
        response = await self.client.post("/v1/systemone", json={
            "state": state, "model": self.model, "questions": wire_questions})
        response.raise_for_status()
        payload = response.json()
        if payload.get("model") != self.model:
            raise ValueError("decision model alias mismatch")
        return validate_answers(questions, restore_choice_order(payload, orders))

    async def close(self) -> None:
        await self.client.aclose()
