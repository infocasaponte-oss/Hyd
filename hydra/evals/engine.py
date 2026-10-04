# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Eval Engine: every new model goes through HYDRA's suites and gets an internal profile.

new model -> coding / reasoning / structured / tool-use / hallucination / vision / latency
          -> internal profile -> Model Registry
"""

from __future__ import annotations

import re
import statistics
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.contracts import HydraRequest, Message, ModelRequest, TaskType
from hydra.memory.embeddings import tokenize
from hydra.providers.adapter import ModelCompiler, extract_json
from hydra.providers.base import ModelProvider
from hydra.registry.models import ModelProfile
from hydra.registry.registry import ModelRegistry
from hydra.tools.registry import ToolRegistry, from_function_name
from hydra.tools.sandbox import Sandbox
from hydra.tools.schema import validate
from hydra.evals.suites import EvalCase, builtin_suites

CODE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
ABSTAIN = re.compile(
    r"(?i)(no (tengo|existe|conozco|hay|encuentro|puedo (verificar|confirmar|encontrar))|"
    r"not (aware|familiar|able to (find|verify))|(doesn'?t|does not|isn'?t|is not) (exist|a real|part of)|"
    r"no such|ficticio|ficticia|fictional|fictitious|inventad|made[- ]up|no estoy seguro|i'?m not sure|"
    r"no (es|forma parte de) (una|la|un)|unknown|desconozco|no dispongo|there is no|no parece existir|"
    r"hypothetical|hipotétic)")

SUITE_TO_TASK = {"coding": TaskType.CODING, "reasoning": TaskType.REASONING, "tool_use": TaskType.TOOL_USE,
                 "vision": TaskType.VISION}


class CaseResult(BaseModel):
    id: str
    suite: str
    passed: bool
    score: float
    latency_ms: float
    detail: str = ""
    output: str = ""


class SuiteResult(BaseModel):
    suite: str
    score: float
    passed: int
    total: int
    mean_latency_ms: float


class EvalReport(BaseModel):
    target: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    suites: dict[str, SuiteResult] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)
    overall: float = 0.0
    latency_p50_ms: float = 0.0
    latency_score: float = 0.0


def _norm(text: str) -> str:
    return " ".join(tokenize(text))


class EvalEngine:
    def __init__(self, providers: dict[str, ModelProvider], sandbox: Sandbox, tools: ToolRegistry | None = None,
                 compiler: ModelCompiler | None = None, suites: dict[str, list[EvalCase]] | None = None,
                 latency_target_ms: float = 3000) -> None:
        self.providers = providers
        self.sandbox = sandbox
        self.tools = tools
        self.compiler = compiler or ModelCompiler()
        self.suites = suites or builtin_suites()
        self.latency_target_ms = latency_target_ms

    # ------------------------------------------------------------------ graders
    async def grade(self, case: EvalCase, text: str, tool_calls: list[dict], structured: Any) -> tuple[bool, float, str]:
        match case.grader:
            case "contains":
                exp = case.expected if isinstance(case.expected, list) else [case.expected]
                ok = any(_norm(str(e)) in _norm(text) for e in exp)
                return ok, float(ok), ""
            case "regex":
                ok = bool(re.search(case.expected, text))
                return ok, float(ok), ""
            case "number":
                nums = NUM.findall(text.replace(",", "."))
                ok = bool(nums) and abs(float(nums[-1]) - float(case.expected)) < 1e-6
                return ok, float(ok), f"last number {nums[-1] if nums else None}"
            case "json_schema":
                try:
                    data = structured if structured is not None else extract_json(text)
                except Exception:
                    return False, 0.0, "no JSON"
                errors = validate(data, case.schema_ or {})
                if errors:
                    return False, 0.25, "; ".join(errors)[:300]
                if isinstance(case.expected, dict):
                    wrong = [k for k, v in case.expected.items() if data.get(k) != v]
                    if wrong:
                        return False, 0.6, f"wrong values: {wrong}"
                return True, 1.0, ""
            case "python_tests":
                m = CODE.search(text)
                code = m.group(1) if m else text
                r = await self.sandbox.execute_python(code + "\n\n" + (case.tests or ""), timeout=20)
                ok = r.exit_code == 0
                return ok, float(ok), (r.stderr[-300:] if not ok else "")
            case "tool_call":
                call = next((c for c in tool_calls if from_function_name(c.get("name", "")) == case.expected), None)
                if call is None:
                    return False, 0.0, f"no call to {case.expected}"
                if self.tools and (t := self.tools.get(case.expected)):
                    errs = validate(call.get("arguments", {}), t.definition.input_schema)
                    if errs:
                        return False, 0.5, "; ".join(errs)
                return True, 1.0, ""
            case "abstain":
                ok = bool(ABSTAIN.search(text))
                return ok, float(ok), "" if ok else "answered a question about something that does not exist"
        return False, 0.0, f"unknown grader {case.grader}"

    # ------------------------------------------------------------------ model evaluation
    async def run_model(self, model: ModelProfile, suites: list[str] | None = None) -> EvalReport:
        provider = self.providers[model.provider]
        report = EvalReport(target=model.id)
        for suite, cases in self.suites.items():
            if suites and suite not in suites:
                continue
            if suite == "vision" and model.capabilities.vision < 0.3 and not model.quirks.native_images:
                continue
            for case in cases:
                report.cases.append(await self._run_case(provider, model, case))
        return self._summarize(report)

    async def _run_case(self, provider: ModelProvider, model: ModelProfile, case: EvalCase) -> CaseResult:
        messages: list[dict] = []
        if case.system:
            messages.append({"role": "system", "content": case.system})
        user: dict = {"role": "user", "content": case.prompt}
        if case.images:
            user["images"] = case.images
        messages.append(user)
        tools = self.tools.specs(set(case.tools)) if (self.tools and case.tools) else None
        req = ModelRequest(messages=messages, temperature=0, max_tokens=case.max_tokens, tools=tools,
                           response_schema=case.schema_ if case.grader == "json_schema" else None,
                           timeout_s=120, metadata={"role": "eval"})
        req = self.compiler.compile(model, req)
        started = time.perf_counter()
        try:
            resp = await provider.generate(model.physical_name, req)
            resp = self.compiler.decompile(req, resp)
        except Exception as exc:
            return CaseResult(id=case.id, suite=case.suite, passed=False, score=0.0,
                              latency_ms=(time.perf_counter() - started) * 1000, detail=f"error: {exc}"[:300])
        latency = (time.perf_counter() - started) * 1000
        ok, score, detail = await self.grade(case, resp.content, resp.tool_calls, resp.structured)
        return CaseResult(id=case.id, suite=case.suite, passed=ok, score=score, latency_ms=round(latency, 1),
                          detail=detail, output=resp.content[:500])

    # ------------------------------------------------------------------ system evaluation (Lab)
    async def run_kernel(self, kernel, suites: list[str] | None = None, label: str = "kernel",
                         **run_kwargs) -> EvalReport:
        """Evaluate the whole HYDRA pipeline (used by HYDRA Lab benchmarks)."""
        report = EvalReport(target=label)
        for suite, cases in self.suites.items():
            if (suites and suite not in suites) or suite == "tool_use":
                continue
            for case in cases:
                msgs = ([Message(role="system", content=case.system)] if case.system else []) + \
                       [Message(role="user", content=case.prompt, images=case.images)]
                started = time.perf_counter()
                try:
                    resp = await kernel.run(HydraRequest(messages=msgs, use_cache=False), **run_kwargs)
                    text = resp.answer
                except Exception as exc:
                    report.cases.append(CaseResult(id=case.id, suite=suite, passed=False, score=0.0,
                                                   latency_ms=(time.perf_counter() - started) * 1000,
                                                   detail=f"error: {exc}"[:300]))
                    continue
                ok, score, detail = await self.grade(case, text, [], None)
                report.cases.append(CaseResult(id=case.id, suite=suite, passed=ok, score=score,
                                               latency_ms=round((time.perf_counter() - started) * 1000, 1),
                                               detail=detail, output=text[:500]))
        return self._summarize(report)

    def _summarize(self, report: EvalReport) -> EvalReport:
        by_suite: dict[str, list[CaseResult]] = {}
        for c in report.cases:
            by_suite.setdefault(c.suite, []).append(c)
        for suite, cs in by_suite.items():
            report.suites[suite] = SuiteResult(
                suite=suite, score=round(sum(c.score for c in cs) / len(cs), 4),
                passed=sum(c.passed for c in cs), total=len(cs),
                mean_latency_ms=round(sum(c.latency_ms for c in cs) / len(cs), 1))
        if report.cases:
            report.latency_p50_ms = round(statistics.median(c.latency_ms for c in report.cases), 1)
            report.latency_score = round(max(0.0, min(1.0, 1 - (report.latency_p50_ms - self.latency_target_ms)
                                                      / (4 * self.latency_target_ms))), 4)
            report.suites["latency"] = SuiteResult(suite="latency", score=report.latency_score,
                                                   passed=int(report.latency_score >= 0.5), total=1,
                                                   mean_latency_ms=report.latency_p50_ms)
        quality = [s.score for k, s in report.suites.items() if k != "latency"]
        report.overall = round(sum(quality) / len(quality), 4) if quality else 0.0
        return report


def apply_to_registry(report: EvalReport, registry: ModelRegistry, weight_runs: int = 25) -> ModelProfile | None:
    """Replace hand-written priors with measured scores (the internal profile)."""
    model = registry.models.get(report.target)
    if model is None:
        return None
    for suite, task in SUITE_TO_TASK.items():
        if suite in report.suites:
            model.learned_quality[task.value] = report.suites[suite].score
            model.runs[task.value] = max(model.runs.get(task.value, 0), weight_runs)
    for extra in ("structured", "hallucination"):
        if extra in report.suites:
            model.learned_quality[f"eval.{extra}"] = report.suites[extra].score
    if report.latency_p50_ms:
        model.estimated_latency_ms = report.latency_p50_ms
    if "structured" in report.suites and report.suites["structured"].score < 0.5:
        model.quirks.native_json_schema = False  # fall back to prompted JSON for this backend
    return model


def summary_table(report: EvalReport) -> list[dict[str, Any]]:
    return [{"suite": s.suite, "score": s.score, "passed": f"{s.passed}/{s.total}",
             "latency_ms": s.mean_latency_ms} for s in report.suites.values()]
