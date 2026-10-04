# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Agreement between independent candidates."""

from __future__ import annotations

import re
from itertools import combinations

from hydra.memory.embeddings import tokenize

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def _final_number(text: str) -> str | None:
    nums = _NUM.findall(text)
    return nums[-1].replace(",", ".") if nums else None


def pair_agreement(a: str, b: str) -> float:
    fa, fb = _final_number(a), _final_number(b)
    if fa is not None and fb is not None and _numbers(a) and _numbers(b):
        if fa == fb:
            return 1.0
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def agreement(answers: list[str]) -> float | None:
    """Mean pairwise agreement; None with fewer than two candidates."""
    answers = [a for a in answers if a and a.strip()]
    if len(answers) < 2:
        return None
    pairs = list(combinations(answers, 2))
    return sum(pair_agreement(a, b) for a, b in pairs) / len(pairs)


def support_for(index: int, answers: list[str], threshold: float = 0.6) -> int:
    """How many other candidates agree with candidate ``index``."""
    return sum(
        1 for j, other in enumerate(answers)
        if j != index and pair_agreement(answers[index], other) >= threshold
    )
