# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Numeric verification for arithmetic questions (Verifier v2: 'maths -> symbolic/numeric check')."""

from __future__ import annotations

import ast
import operator
import re

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

ARITH = re.compile(r"(-?\d+(?:\.\d+)?(?:\s*[-+*/×x÷^%]\s*-?\d+(?:\.\d+)?)+)")
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def safe_arith(expr: str) -> float | int | None:
    expr = expr.replace("×", "*").replace("x", "*").replace("÷", "/").replace("^", "**")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported")

    try:
        return ev(ast.parse(expr.strip(), mode="eval"))
    except Exception:
        return None


MATH_CUE = re.compile(r"cu[áa]nto (?:es|da|son|vale)|calcul|resultado|opera|how much|comput|evaluat|=", re.I)
# "Ley 5/2007", "TRM/844/2026" (official numbers) and "4/11/2003" (dates) are not divisions.
NUMBER_OR_DATE = re.compile(r"\d+(?:/\d+)*/(?:1[89]|20)\d\d")


def _part_of_identifier(text: str, start: int, end: int) -> bool:
    """Digits glued to letters, slashes or hyphenated codes (BOE-A-2003-20254, TRM/844/2026)."""
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    if before.isalnum() or before in "/_" or after.isalnum() or after in "/_":
        return True
    return before == "-" and start > 1 and text[start - 2].isalnum()


def expected_value(question: str) -> tuple[str, float] | None:
    """The arithmetic expression in a question and its exact value, if any.

    Official numbers, dates and codes are skipped unless the question explicitly asks to calculate.
    """
    explicit = MATH_CUE.search(question) is not None
    for m in ARITH.finditer(question):
        expr = m.group(1)
        if not explicit and (_part_of_identifier(question, m.start(1), m.end(1))
                             or NUMBER_OR_DATE.fullmatch(expr.strip().lstrip("-"))):
            continue
        value = safe_arith(expr)
        if value is not None:
            return expr.strip(), float(value)
    return None


def answer_matches(answer: str, value: float, rel: float = 1e-6) -> bool:
    for n in NUM.findall(answer.replace(" ", "").replace(" ", "")):
        try:
            x = float(n.replace(",", "."))
        except ValueError:
            continue
        if abs(x - value) <= max(rel * abs(value), 1e-9):
            return True
    return False
