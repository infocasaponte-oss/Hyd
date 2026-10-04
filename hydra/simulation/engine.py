# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Simulation Engine: before acting, predict the consequences and compare alternatives.

Deterministic dry-runs where the world allows it (file diffs, ``git apply --check``,
SQL query plans, static analysis of code); the planner can rank candidate actions
by predicted risk before executing any of them.
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import sqlite3

from pydantic import BaseModel, Field

from hydra.tools.definitions import ToolCall, ToolContext, ToolDefinition
from hydra.tools.policy import allowed_path

DANGEROUS_MODULES = {"os", "subprocess", "shutil", "socket", "ctypes", "multiprocessing", "requests",
                     "urllib", "http", "pathlib", "signal", "sys"}
DANGEROUS_CALLS = {"exec", "eval", "compile", "__import__", "open", "system", "popen", "remove", "unlink",
                   "rmtree", "kill", "rename", "chmod"}


class SimulationResult(BaseModel):
    tool: str
    ok: bool
    reversible: bool
    risk: float = Field(ge=0, le=1)
    summary: str
    predicted_effects: list[str] = Field(default_factory=list)
    dry_run_output: str = ""


class Simulator:
    def __init__(self, min_risk: int = 2) -> None:
        self.min_risk = min_risk

    def should_simulate(self, d: ToolDefinition) -> bool:
        return d.writes or d.risk_level >= self.min_risk

    async def simulate(self, call: ToolCall, d: ToolDefinition, ctx: ToolContext) -> SimulationResult:
        handler = {
            "filesystem.write": self._fs_write,
            "git.apply_patch": self._git_patch,
            "sql.query_readonly": self._sql,
            "python.execute": self._python,
        }.get(d.name)
        if handler is None:
            return SimulationResult(tool=d.name, ok=True, reversible=not d.writes,
                                    risk=min(1.0, d.risk_level / 5), summary="no simulator; policy checks only")
        try:
            return await handler(call, ctx)
        except Exception as exc:  # simulation must never crash the task
            return SimulationResult(tool=d.name, ok=True, reversible=False, risk=0.6,
                                    summary=f"simulation unavailable: {exc}")

    async def compare(self, calls: list[tuple[ToolCall, ToolDefinition]], ctx: ToolContext
                      ) -> list[tuple[ToolCall, SimulationResult]]:
        """Simulate alternative actions and rank them: feasible first, then lowest risk."""
        results = [(c, await self.simulate(c, d, ctx)) for c, d in calls]
        return sorted(results, key=lambda x: (not x[1].ok, x[1].risk, not x[1].reversible))

    # ------------------------------------------------------------------ handlers
    async def _fs_write(self, call: ToolCall, ctx: ToolContext) -> SimulationResult:
        path = allowed_path(ctx, call.arguments["path"])
        if path is None:
            return SimulationResult(tool="filesystem.write", ok=False, reversible=True, risk=1.0,
                                    summary="path outside allowed scope")
        new = call.arguments["content"]
        if path.exists():
            old = path.read_text(encoding="utf-8", errors="replace")
            diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                f"a/{call.arguments['path']}", f"b/{call.arguments['path']}"))
            removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
            added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
            total = max(1, len(old.splitlines()))
            risk = min(1.0, 0.2 + removed / total)
            return SimulationResult(
                tool="filesystem.write", ok=True, reversible=False, risk=round(risk, 3),
                summary=f"overwrite {call.arguments['path']}: +{added} -{removed} lines",
                predicted_effects=[f"modify {call.arguments['path']}"], dry_run_output=diff[:8000])
        return SimulationResult(tool="filesystem.write", ok=True, reversible=True, risk=0.1,
                                summary=f"create {call.arguments['path']} ({len(new)} chars)",
                                predicted_effects=[f"create {call.arguments['path']}"])

    async def _git_patch(self, call: ToolCall, ctx: ToolContext) -> SimulationResult:
        root = allowed_path(ctx, ".")
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(root), "apply", "--check", "--stat", "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate(call.arguments["patch"].encode())
        ok = proc.returncode == 0
        stat = out.decode("utf-8", "replace")
        files = [line.split("|")[0].strip() for line in stat.splitlines() if "|" in line]
        return SimulationResult(
            tool="git.apply_patch", ok=ok, reversible=True, risk=0.3 if ok else 1.0,
            summary=("patch applies cleanly" if ok else "patch does not apply: " + err.decode()[:300]),
            predicted_effects=[f"modify {f}" for f in files], dry_run_output=stat[:4000])

    async def _sql(self, call: ToolCall, ctx: ToolContext) -> SimulationResult:
        db = allowed_path(ctx, call.arguments["database"])
        if db is None or not db.exists():
            return SimulationResult(tool="sql.query_readonly", ok=False, reversible=True, risk=1.0,
                                    summary="database not found in scope")

        def plan():
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                return [" ".join(map(str, r)) for r in con.execute("EXPLAIN QUERY PLAN " + call.arguments["query"])]
            finally:
                con.close()

        try:
            rows = await asyncio.to_thread(plan)
        except sqlite3.Error as exc:
            return SimulationResult(tool="sql.query_readonly", ok=False, reversible=True, risk=0.5,
                                    summary=f"query invalid: {exc}")
        full_scan = any("SCAN" in r and "INDEX" not in r for r in rows)
        return SimulationResult(tool="sql.query_readonly", ok=True, reversible=True,
                                risk=0.2 if full_scan else 0.05,
                                summary="full table scan" if full_scan else "indexed query",
                                dry_run_output="\n".join(rows))

    async def _python(self, call: ToolCall, ctx: ToolContext) -> SimulationResult:
        code = call.arguments["code"]
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return SimulationResult(tool="python.execute", ok=False, reversible=True, risk=0.0,
                                    summary=f"syntax error line {exc.lineno}: {exc.msg}")
        imports, calls = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in DANGEROUS_CALLS:
                    calls.add(name)
        risky = sorted(imports & DANGEROUS_MODULES) + sorted(calls)
        risk = min(1.0, 0.1 + 0.15 * len(risky))
        return SimulationResult(
            tool="python.execute", ok=True, reversible=True, risk=round(risk, 3),
            summary=("pure computation" if not risky else "uses " + ", ".join(risky)),
            predicted_effects=[f"calls {r}" for r in risky])
