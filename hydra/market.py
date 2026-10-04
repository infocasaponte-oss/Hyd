# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Capability Market + deterministic-first solvers.

Models are not special: a capability (``solve_symbolic_equation``, ``translate_spanish``...)
can be provided by an LLM, a VLM, a tool, a human, an external API, an algorithm or a
database. The market resolves the best provider; if a deterministic solver exists and is
certain it wins over any model (cheaper, faster, no hallucinations)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from pydantic import BaseModel

from hydra.verification.math_check import safe_arith


class CapabilityProvider(BaseModel):
    id: str
    capability: str
    provider_type: str  # llm | vlm | tool | human | external_api | algorithm | database
    quality: float = 0.7
    latency_ms: float = 1000
    cost: float = 0.0
    availability: float = 1.0
    deterministic: bool = False
    local: bool = True


class SolverResult(BaseModel):
    solver: str
    input: str
    output: Any
    answer: str
    confidence: float = 1.0
    duration_ms: float = 0.0


QUESTION = re.compile(r"(?i)^\s*(?:¿\s*)?(?:cu[aá]nto\s+(?:es|son|da)|calcula(?:r)?|what\s+is|compute|calculate|"
                      r"evaluate|eval[uú]a)\s*:?\s*(?P<expr>.+?)\s*\??\s*$")
PURE_EXPR = re.compile(r"^[\d\s.,+\-*/×÷x^()%]+$")
PERCENT = re.compile(r"(?i)^\s*(?:¿\s*)?(?:cu[aá]nto\s+es\s+(?:el\s+)?|what\s+is\s+)?(?P<p>\d+(?:[.,]\d+)?)\s*%\s*"
                     r"(?:de|of)\s+(?P<n>\d+(?:[.,]\d+)?)\s*\??\s*$")
EQUATION = re.compile(r"(?i)^\s*(?:resuelve|solve|despeja|halla\s+x\s+en)\s*:?\s*(?P<eq>[^=]+=[^=]+?)\s*\.?\s*$")
DERIVATIVE = re.compile(r"(?i)^\s*(?:deriva(?:da\s+de)?|derivative\s+of|differentiate|d/dx)\s*:?\s*(?P<f>.+?)\s*\.?\s*$")
JSON_CHECK = re.compile(r"(?is)^\s*(?:¿\s*)?(?:es\s+(?:un\s+)?json\s+v[aá]lido|is\s+(?:this\s+)?valid\s+json|valida\s+"
                        r"(?:este\s+)?json)\s*\??\s*:?\s*(?P<doc>[\[{].*[\]}])\s*\??\s*$")
SQL_CHECK = re.compile(r"(?is)^\s*(?:¿\s*)?(?:es\s+v[aá]lid[oa]\s+(?:esta\s+consulta\s+|este\s+)?sql|is\s+(?:this\s+)?"
                       r"(?:sql|query)\s+valid)\s*\??\s*:?\s*(?P<sql>.+?)\s*$")


def _num(v: float) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


class DeterministicSolvers:
    """Only answers when certain; otherwise returns None and the models take over."""

    def solve(self, text: str) -> SolverResult | None:
        t0 = time.perf_counter()
        for fn in (self._numeric_sort, self._percent, self._arith, self._equation, self._derivative, self._json, self._sql):
            try:
                r = fn(text.strip())
            except Exception:
                r = None
            if r is not None:
                r.duration_ms = round((time.perf_counter() - t0) * 1000, 3)
                return r
        return None

    def _numeric_sort(self, text: str) -> SolverResult | None:
        """A complete, unambiguous read-only command. Never evaluates Python or infers missing items."""
        import math
        match = re.fullmatch(r"(?:ordena|ordenar|sort)\s+(?:de menor a mayor|ascendente|ascending)\s*:?\s*"
                             r"(?P<items>\[[^\[\]]*\])\s*(?:[.;]\s*)?(?:como\s+(?:lista\s+)?json|en\s+json)?\s*[.]?", text, re.I)
        if not match:
            return None
        if len(match["items"]) > 10000:
            return None
        values = json.loads(match["items"])
        if not isinstance(values,list) or len(values) > 256:
            return None
        if any(type(v) not in (int,float) or (type(v) is float and not math.isfinite(v)) for v in values):
            return None
        result = sorted(values)
        return SolverResult(solver="numeric_sort",input=match["items"],output=result,
                            answer=json.dumps(result,ensure_ascii=False,separators=(",", ":")))

    def _arith(self, text: str) -> SolverResult | None:
        m = QUESTION.match(text)
        expr = m.group("expr") if m else (text if PURE_EXPR.match(text) and re.search(r"\d\s*[-+*/×÷x^]\s*\d", text)
                                          else None)
        if not expr or not PURE_EXPR.match(expr) or not re.search(r"\d", expr):
            return None
        value = safe_arith(expr)
        if value is None:
            return None
        return SolverResult(solver="calculator", input=expr, output=value, answer=f"{expr.strip()} = {_num(value)}")

    def _percent(self, text: str) -> SolverResult | None:
        m = PERCENT.match(text)
        if not m:
            return None
        p, n = float(m.group("p").replace(",", ".")), float(m.group("n").replace(",", "."))
        v = p * n / 100
        return SolverResult(solver="calculator", input=text, output=v,
                            answer=f"{_num(p)}% de {_num(n)} = {_num(v)}")

    def _equation(self, text: str) -> SolverResult | None:
        m = EQUATION.match(text)
        if not m:
            return None
        import sympy as sp

        left, right = m.group("eq").replace("^", "**").split("=", 1)
        tr = sp.parsing.sympy_parser.standard_transformations + (
            sp.parsing.sympy_parser.implicit_multiplication_application,)
        lhs = sp.parsing.sympy_parser.parse_expr(left, transformations=tr)
        rhs = sp.parsing.sympy_parser.parse_expr(right, transformations=tr)
        syms = sorted((lhs - rhs).free_symbols, key=str)
        if len(syms) != 1:
            return None
        sol = sp.solve(sp.Eq(lhs, rhs), syms[0])
        if not sol:
            return None
        vals = ", ".join(str(s) for s in sol)
        return SolverResult(solver="sympy.solve", input=m.group("eq"), output=[str(s) for s in sol],
                            answer=f"{syms[0]} = {vals}")

    def _derivative(self, text: str) -> SolverResult | None:
        m = DERIVATIVE.match(text)
        if not m:
            return None
        import sympy as sp

        tr = sp.parsing.sympy_parser.standard_transformations + (
            sp.parsing.sympy_parser.implicit_multiplication_application,)
        f = sp.parsing.sympy_parser.parse_expr(m.group("f").replace("^", "**"), transformations=tr)
        syms = sorted(f.free_symbols, key=str)
        if len(syms) != 1:
            return None
        d = sp.diff(f, syms[0])
        return SolverResult(solver="sympy.diff", input=m.group("f"), output=str(d),
                            answer=f"d/d{syms[0]} ({f}) = {d}")

    def _json(self, text: str) -> SolverResult | None:
        m = JSON_CHECK.match(text)
        if not m:
            return None
        try:
            json.loads(m.group("doc"))
            return SolverResult(solver="json.validate", input=m.group("doc")[:200], output=True,
                                answer="Sí, es JSON válido.")
        except json.JSONDecodeError as e:
            return SolverResult(solver="json.validate", input=m.group("doc")[:200], output=False,
                                answer=f"No, no es JSON válido: {e.msg} (línea {e.lineno}, columna {e.colno}).")

    def _sql(self, text: str) -> SolverResult | None:
        m = SQL_CHECK.match(text)
        if not m:
            return None
        sql = m.group("sql").strip().strip("`")
        ok = sqlite3.complete_statement(sql if sql.endswith(";") else sql + ";")
        if not ok:
            return SolverResult(solver="sql.parse", input=sql[:200], output=False,
                                answer="No: la sentencia SQL está incompleta.")
        con = sqlite3.connect(":memory:")
        try:
            con.execute(f"EXPLAIN {sql}")
            return SolverResult(solver="sql.parse", input=sql[:200], output=True, answer="Sí, la sintaxis SQL es válida.")
        except sqlite3.OperationalError as e:
            msg = str(e)
            if "no such table" in msg or "no such column" in msg:
                return SolverResult(solver="sql.parse", input=sql[:200], output=True, confidence=0.9,
                                    answer=f"La sintaxis es válida (SQLite); el esquema no está disponible: {msg}.")
            return SolverResult(solver="sql.parse", input=sql[:200], output=False,
                                answer=f"No, la sintaxis SQL no es válida: {msg}.")
        finally:
            con.close()


class CapabilityMarket:
    def __init__(self, solvers: DeterministicSolvers | None = None) -> None:
        self.providers: list[CapabilityProvider] = []
        self.solvers = solvers or DeterministicSolvers()
        for cap in ("reasoning.arithmetic", "reasoning.symbolic", "tool_use.schema_following", "coding.sql"):
            self.providers.append(CapabilityProvider(id=f"solver:{cap}", capability=cap, provider_type="algorithm",
                                                     quality=0.999, latency_ms=2, deterministic=True))

    def register(self, p: CapabilityProvider) -> None:
        self.providers = [x for x in self.providers if x.id != p.id] + [p]

    def sync_registry(self, registry, tools=None) -> int:
        n = 0
        for m in registry.all():
            if not m.enabled:
                continue
            for cap in ("chat", "reasoning", "coding", "vision", "tools", "research", "routing"):
                q = getattr(m.capabilities, cap)
                if q > 0:
                    self.register(CapabilityProvider(id=f"model:{m.id}:{cap}", capability=cap,
                                                     provider_type="vlm" if cap == "vision" else "llm", quality=q,
                                                     latency_ms=m.predicted_latency_ms,
                                                     cost=m.output_cost, local=m.local))
                    n += 1
        for name in (tools.names() if tools else []):
            self.register(CapabilityProvider(id=f"tool:{name}", capability=f"tool.{name}", provider_type="tool",
                                             quality=0.95, latency_ms=200, deterministic=name == "json.validate"))
        return n

    def resolve(self, capability: str, *, local_only: bool = False, min_quality: float = 0.0,
                max_latency_ms: float | None = None, weights: dict[str, float] | None = None
                ) -> list[CapabilityProvider]:
        w = weights or {"quality": 1.0, "latency": 0.15, "cost": 0.2, "deterministic": 0.3}
        cands = [p for p in self.providers
                 if (p.capability == capability or p.capability.startswith(capability + ".")
                     or capability.startswith(p.capability + "."))
                 and p.quality >= min_quality and (p.local or not local_only)
                 and (max_latency_ms is None or p.latency_ms <= max_latency_ms) and p.availability > 0]
        return sorted(cands, key=lambda p: -(w["quality"] * p.quality - w["latency"] * min(1, p.latency_ms / 30000)
                                             - w["cost"] * min(1, p.cost / 20) + w["deterministic"] * p.deterministic))
