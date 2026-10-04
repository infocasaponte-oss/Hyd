# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded, isolated typed decision engine with explicit abstention."""
from __future__ import annotations

import math
import time

from hydra.hyd.model import CandidateRanker, render


def typed_confidence(kind: str, probabilities: dict[str, float]) -> float:
    """Public contract confidence, distinct from the maximum calibrated probability."""
    size = len(probabilities)
    if size == 1:
        return 1.0
    peak = max(probabilities.values())
    if kind == "choice":
        return max(0.0, min(1.0, (size * peak - 1) / (size - 1)))
    if kind == "score":
        mode = min(probabilities, key=lambda key: (-probabilities[key], int(key)))
        midpoint = (size - 1) / 2
        uniform_deviation = math.fsum(abs(i - midpoint) for i in range(size)) / size
        deviation = math.fsum(p * abs(int(key) - int(mode)) for key, p in probabilities.items())
        return max(0.0, min(1.0, 1 - deviation / uniform_deviation))
    return peak


class HydEngine:
    model = "hyd-latest"

    def __init__(self, ranker: CandidateRanker, min_confidence: float = .95, min_margin: float = .1):
        if not 0 <= min_confidence <= 1 or not 0 <= min_margin <= 1:
            raise ValueError("invalid Hyd abstention thresholds")
        self.ranker = ranker
        self.min_confidence, self.min_margin = min_confidence, min_margin

    def admit(self, state, questions: dict):
        if not isinstance(questions, dict) or not 1 <= len(questions) <= 64:
            raise ValueError("Hyd requires 1..64 questions")
        if len(render(state)) > 50000:
            raise ValueError("Hyd state exceeds 50000 characters")
        plans = []
        total_chars = 0
        for key, question in questions.items():
            if not isinstance(key, str) or not key or not isinstance(question, dict):
                raise ValueError("invalid Hyd question")
            kind, criteria = question.get("type"), question.get("criteria")
            if kind == "choice":
                if not isinstance(criteria, dict) or not all(isinstance(k, str) and k for k in criteria):
                    raise ValueError("choice requires named criteria")
                options = criteria
            elif kind == "noul":
                if criteria is not None and (not isinstance(criteria, dict) or set(criteria) - {"false", "true"}):
                    raise ValueError("noul criteria must name false/true")
                options = {"false": (criteria or {}).get("false", "false"),
                           "true": (criteria or {}).get("true", "true")}
            elif kind == "score":
                if not isinstance(criteria, list):
                    raise ValueError("score requires ordered criteria")
                options = {str(i): value for i, value in enumerate(criteria)}
            else:
                raise ValueError("unknown Hyd question type")
            if not 1 <= len(options) <= 255:
                raise ValueError("Hyd requires 1..255 options")
            instructions = question.get("instructions")
            total_chars += len(render(options)) + len(render(instructions))
            if total_chars > 100000:
                raise ValueError("Hyd question budget exceeded")
            plans.append((key, kind, options, instructions))
        return plans, total_chars

    def decide(self, state, questions: dict, deadline=None) -> dict:
        plans, total_chars = self.admit(state, questions)
        answers, input_tokens = {}, 0
        for key, kind, options, instructions in plans:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Hyd deadline exceeded")
            probabilities = self.ranker.probabilities(state, instructions, options, deadline=deadline)
            input_tokens += getattr(self.ranker, "last_input_tokens", 0)
            # Stable tie-breaking by identifier, independent of submitted order.
            selected = min(probabilities, key=lambda k: (-probabilities[k], int(k) if kind == "score" else k))
            confidence = probabilities[selected]
            ordered = sorted(probabilities.values(), reverse=True)
            margin = ordered[0] - ordered[1] if len(ordered) > 1 else 0.0
            supported = self._supported(kind, options, instructions, questions[key].get("criteria"))
            abstained = not supported or confidence < self.min_confidence or margin < self.min_margin
            answer = {"type": kind, "probabilities": probabilities, "confidence": typed_confidence(kind, probabilities),
                      "selection_probability": confidence,
                      "margin": margin, "abstained": abstained,
                      "reason": "unsupported_domain" if not supported else "low_confidence" if abstained else "accepted"}
            if kind == "choice":
                answer["choice"] = selected
            elif kind == "noul":
                answer["noul"] = probabilities["true"]
            else:
                answer["score"] = math.fsum(int(k) * p for k, p in probabilities.items())
                answer["legend"] = dict(options)
            answers[key] = answer
        return {"model": self.model, "model_revision": self.ranker.revision,
                "answers": answers, "generation_tokens": 0,
                "usage": {"input_tokens": input_tokens, "output_tokens": 0,
                          "input_characters": len(render(state)), "question_characters": total_chars}}

    def _supported(self, kind, options, instructions, criteria):
        # An API shape does not imply a trained semantic domain. The first model
        # certifies only the exact routing vocabulary; generic decisions abstain.
        trained = self.ranker.training.get("criteria", {})
        routing = kind == "choice" and instructions is None and len(options) > 1 and options == trained
        domain = {"type": kind, "criteria": criteria, "instructions": instructions}
        return routing or domain in self.ranker.training.get("question_domains", [])
