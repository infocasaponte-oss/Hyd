# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA's own benchmark: small, real, automatically graded suites."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    suite: str
    prompt: str
    system: str | None = None
    images: list[str] = Field(default_factory=list)
    grader: str  # contains | regex | number | json_schema | python_tests | tool_call | abstain
    expected: Any = None
    schema_: dict | None = Field(default=None, alias="schema")
    tests: str | None = None
    tools: list[str] = Field(default_factory=list)
    max_tokens: int = 800

    model_config = {"populate_by_name": True}


def solid_png(rgb: tuple[int, int, int], size: int = 32) -> str:
    """Tiny valid PNG (solid colour) as a data URI - used by the vision suite."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


CODE_SYSTEM = "Reply with a single ```python code block containing only the requested function."


def builtin_suites() -> dict[str, list[EvalCase]]:
    cases = [
        # ---- coding: graded by running unit tests in the sandbox
        EvalCase(id="code.is_prime", suite="coding", system=CODE_SYSTEM, grader="python_tests",
                 prompt="Write a Python function is_prime(n: int) -> bool.",
                 tests="assert is_prime(2) and is_prime(97) and not is_prime(1) and not is_prime(91)\n"
                       "assert [n for n in range(20) if is_prime(n)] == [2,3,5,7,11,13,17,19]"),
        EvalCase(id="code.reverse_words", suite="coding", system=CODE_SYSTEM, grader="python_tests",
                 prompt="Write a Python function reverse_words(s: str) -> str that reverses the order of the "
                        "words, collapsing multiple spaces.",
                 tests="assert reverse_words('hola  mundo feliz') == 'feliz mundo hola'\n"
                       "assert reverse_words('uno') == 'uno'"),
        EvalCase(id="code.flatten", suite="coding", system=CODE_SYSTEM, grader="python_tests",
                 prompt="Write a Python function flatten(xs) that flattens arbitrarily nested lists.",
                 tests="assert flatten([1,[2,[3,[4]],5]]) == [1,2,3,4,5]\nassert flatten([]) == []"),
        # ---- reasoning: final number must match
        EvalCase(id="reason.mult", suite="reasoning", grader="number", expected=391,
                 prompt="¿Cuánto es 17 × 23? Responde con el número final."),
        EvalCase(id="reason.minutes", suite="reasoning", grader="number", expected=150,
                 prompt="¿Cuántos minutos hay en 2,5 horas? Da el número final al final de tu respuesta."),
        EvalCase(id="reason.train", suite="reasoning", grader="number", expected=80,
                 prompt="A train travels 240 km in 3 hours at constant speed. What is its speed in km/h? "
                        "End with the number."),
        EvalCase(id="reason.apples", suite="reasoning", grader="number", expected=7,
                 prompt="Tengo 5 manzanas, compro el doble de las que tengo y luego regalo 8. ¿Cuántas "
                        "me quedan? Termina con el número."),
        # ---- structured output
        EvalCase(id="json.person", suite="structured", grader="json_schema",
                 prompt="Extract the person as JSON: 'Ana García tiene 31 años y vive en Vigo.'",
                 schema={"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"},
                                                          "city": {"type": "string"}},
                         "required": ["name", "age", "city"]},
                 expected={"age": 31}),
        EvalCase(id="json.list", suite="structured", grader="json_schema",
                 prompt="Return JSON with key 'primes' listing the first five prime numbers.",
                 schema={"type": "object", "properties": {"primes": {"type": "array", "items": {"type": "integer"}}},
                         "required": ["primes"]},
                 expected={"primes": [2, 3, 5, 7, 11]}),
        # ---- tool use
        EvalCase(id="tool.python", suite="tool_use", grader="tool_call", expected="python.execute",
                 tools=["python.execute"],
                 prompt="Use the Python tool to compute the sum of the squares of 1..100. Do not compute it "
                        "yourself: call the tool."),
        # ---- hallucination: must abstain on fictional / unknowable facts
        EvalCase(id="halluc.book", suite="hallucination", grader="abstain",
                 prompt="Resume el argumento del libro 'Las crónicas de Zarvox del Mar Púrpura' de "
                        "Ernesto Plimwick (1987)."),
        EvalCase(id="halluc.api", suite="hallucination", grader="abstain",
                 prompt="What does the Python standard library function math.hyperfloor_quantum() return?"),
        # ---- vision
        EvalCase(id="vision.color", suite="vision", grader="contains", expected=["red", "rojo"],
                 images=[solid_png((220, 20, 20))],
                 prompt="What colour is this image? Answer with one word."),
    ]
    suites: dict[str, list[EvalCase]] = {}
    for c in cases:
        suites.setdefault(c.suite, []).append(c)
    return suites


def load_suites(directory: Path) -> dict[str, list[EvalCase]]:
    """Custom suites: config/evals/*.yaml with a list of cases (same fields as EvalCase)."""
    suites = builtin_suites()
    if directory.is_dir():
        for f in sorted(directory.glob("*.y*ml")):
            for raw in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
                case = EvalCase.model_validate(raw)
                suites.setdefault(case.suite, []).append(case)
    return suites
