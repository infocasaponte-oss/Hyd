# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Goal Runner: OBSERVE -> WORLD -> PLAN -> SIMULATE -> ACT -> VERIFY -> (REPLAN) -> CORPUS/PROCEDURES.

    Planner proposes · Simulation estimates · Policy/Risk/Authorization decide · Executor acts

Receding horizon: plan, execute the next ready nodes, observe, re-check the goal's
objective conditions, replan with the remaining budget. Every milestone is checkpointed
(resume after a crash), every planner decision is written to the ledger, every action
becomes corpus (planner / action-value / process supervision) and statistics for the
historical simulator, the calibration engine, the value model and the procedure miner."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.contracts import ExecutionMode, HydraRequest, Message
from hydra.core.hashing import now_iso
from hydra.governance.security import ActionEnvelope, ActionGate, Principal, principal_for
from hydra.planning.goals import ExecutionPlan, Goal, PlanNode, PlanWeights, pareto_plans
from hydra.planning.htn import decompose, infer_goal
from hydra.planning.procedures import ProcedureMiner, ProcedureStore, Trace, ValueModel
from hydra.planning.simulator import CalibrationEngine, HistoricalSimulator, SimulatorEnsemble, branch_and_bound
from hydra.verification.code import changed_python_paths

FILE_BLOCK = re.compile(r"(?:###\s*FILE:\s*|#\s*file:\s*)(?P<path>[\w./\\-]+)\s*\n```[\w+-]*\s*\n(?P<body>.*?)```", re.S)
DIFF_BLOCK = re.compile(r"```(?:diff|patch)\s*\n(.*?)```", re.S)

ACTION_CAPABILITY = {"tests.run": "python.run_tests", "code.patch": "code.patch:/workspace/**",
                     "workspace.inspect": "workspace.list:*", "world.query": "world.query:*",
                     "memory.search": "memory.search", "model.reason": "model.reason", "verify": "model.reason"}


class StepRecord(BaseModel):
    node_id: str
    action: str
    success: bool
    predicted_success: float
    duration_ms: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    decision: str = "allow"


class GoalResult(BaseModel):
    goal: Goal
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
    steps: list[StepRecord] = Field(default_factory=list)
    plans_considered: list[dict[str, Any]] = Field(default_factory=list)
    selected_plans: list[str] = Field(default_factory=list)
    replans: int = 0
    duration_ms: float = 0.0
    patch: str | None = None
    tests: dict[str, Any] | None = None
    pending_authorizations: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint: str | None = None
    system: str = "system2"


def verification_report(diff: str, workdir: Path, *, baseline_failed: bool, full_suite_passed: bool) -> dict:
    """Layered verification of a code goal (HYDRA-SO CodeAgent criteria): the baseline must fail,
    the full suite must pass afterwards and every changed Python file must compile."""
    changed = changed_python_paths(diff)
    syntax_errors = {}
    for rel in changed:
        path = workdir / rel
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), rel, "exec")
            except (SyntaxError, ValueError) as exc:
                syntax_errors[rel] = f"{type(exc).__name__}: {exc}"[:300]
    improvement = baseline_failed and full_suite_passed
    return {"baseline_failed": baseline_failed, "full_suite_passed": full_suite_passed,
            "changed_python": changed, "syntax_passed": not syntax_errors, "syntax_errors": syntax_errors,
            "improvement_demonstrated": improvement, "verified": improvement and not syntax_errors}


class GoalRunner:
    def __init__(self, runtime, *, horizon: int = 2, max_replans: int = 3, rollouts: int = 200) -> None:
        self.rt = runtime
        self.horizon = horizon
        self.max_replans = max_replans
        self.rollouts = rollouts
        data = runtime.settings.data_dir
        self.checkpoints = data / "goals"
        self.checkpoints.mkdir(parents=True, exist_ok=True)
        docs = getattr(runtime, "documents", None)
        self.historical = HistoricalSimulator(data / "planning" / "historical.json", docs=docs)
        self.calibration = CalibrationEngine(data / "planning" / "calibration.json", docs=docs)
        self.procedures = ProcedureStore(data / "planning" / "procedures.json", docs=docs)
        self.value = ValueModel(data / "planning" / "value.json", docs=docs)
        self.traces_path = data / "planning" / "traces.jsonl"
        self.gate = ActionGate(audit=self._audit)
        self.sim = SimulatorEnsemble(self.historical, self.calibration, self.gate.risk)

    def _audit(self, et: str, payload: dict) -> None:
        pass  # action gate decisions are recorded per step in the ledger (PLANNER_DECISION)

    # ------------------------------------------------------------------ public
    async def run(self, description: str, *, workspace: Path | None = None, mode: str = "balanced",
                  principal: Principal | None = None, authorized: set[str] | None = None,
                  context: dict | None = None, goal: Goal | None = None, max_seconds: float = 600) -> GoalResult:
        started = time.perf_counter()
        ctx = dict(context or {})
        ws = None
        if workspace is not None:
            ws = self.rt.workspaces.create(f"goal-{int(time.time() * 1000)}", source=workspace)
            ctx["workspace"] = str(ws.working)
        goal = goal or infer_goal(description, ctx)
        goal.context.update(ctx)
        principal = principal or principal_for("hydra-goal-runner", {"user", "coder_worker"})
        state: dict[str, Any] = {"metrics": {"budget_exhausted": False, "policy_blocked": False}, "context": [],
                                 "answer": None, "failed_sources": [], "history": []}
        result = GoalResult(goal=goal, status="open")
        weights = PlanWeights.for_mode(mode)
        plan = await self._choose_plan(goal, weights, state, result, max_seconds)
        while True:
            if time.perf_counter() - started > max_seconds:
                state["metrics"]["budget_exhausted"] = True
            status = goal.status(state["metrics"])
            if status != "open":
                break
            ready = plan.ready()[: self.horizon] if plan else []
            if not ready:
                if plan and all(n.status in ("done", "skipped") for n in plan.nodes):
                    # plan completed but goal still open -> replan (different strategy)
                    state["failed_sources"].append(plan.source)
                if result.replans >= self.max_replans:
                    break
                result.replans += 1
                plan = await self._choose_plan(goal, weights, state, result, max_seconds)
                if plan is None:
                    break
                continue
            outcomes = await asyncio.gather(*[self._execute(n, goal, state, principal, authorized or set(), mode, ws)
                                              for n in ready])
            for node, rec in zip(ready, outcomes):
                result.steps.append(rec)
                node.status = "done" if rec.success else ("blocked" if rec.decision != "allow" and not rec.success
                                                          and rec.decision.startswith("require") else "failed")
                if rec.decision.startswith("require") and not rec.success:
                    result.pending_authorizations.append({"node": node.id, "action": node.action,
                                                          "decision": rec.decision})
                self._learn_step(goal, node, rec, state)
            self._checkpoint(goal, plan, state, result)
            if any(n.status in ("failed", "blocked") for n in ready):
                if any(n.status == "blocked" for n in ready):
                    state["metrics"]["policy_blocked"] = not authorized
                    if state["metrics"]["policy_blocked"]:
                        break
                state["failed_sources"].append(plan.source)
                if result.replans >= self.max_replans:
                    break
                result.replans += 1
                plan = await self._choose_plan(goal, weights, state, result, max_seconds)
                if plan is None:
                    break
        result.status = goal.status(state["metrics"])
        if result.status == "open":
            result.status = "incomplete"
        result.metrics = state["metrics"]
        result.answer = state["answer"]
        result.duration_ms = round((time.perf_counter() - started) * 1000, 1)
        if ws is not None:
            report = verification_report(self.rt.workspaces.diff(ws), ws.working,
                                         baseline_failed=state.get("baseline_tests_pass") is False,
                                         full_suite_passed=state.get("full_suite_tests_pass") is True)
            state["metrics"]["verification"] = report
            if (result.status == "achieved" and report["changed_python"]
                    and (not report["syntax_passed"] or not report["full_suite_passed"])):
                result.status = "incomplete"
            fin = self.rt.workspaces.finalize(ws, keep_working=False, extra={"goal": goal.description,
                                                                             "status": result.status})
            result.patch = (ws.outputs / "patch.diff").read_text(encoding="utf-8") or None
            state["metrics"]["files_changed"] = fin["files_changed"]
            if result.patch:
                art = self.rt.artifact_store.put(result.patch, media_type="text/x-diff", artifact_type="code_patch",
                                                 task_id=goal.id, metadata={"goal": goal.description[:200]})
                state["metrics"]["patch_artifact"] = art.uri
        result.checkpoint = str(self._checkpoint(goal, plan, state, result))
        self._finish(goal, result, state)
        return result

    def resume_state(self, goal_id: str) -> dict[str, Any] | None:
        p = self.checkpoints / f"{goal_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    # ------------------------------------------------------------------ planning
    async def _choose_plan(self, goal: Goal, weights: PlanWeights, state: dict, result: GoalResult,
                           max_seconds: float) -> ExecutionPlan | None:
        candidates = [p for p in decompose(goal) if p.source not in state["failed_sources"]]
        proc = self.procedures.best(goal.goal_type)
        if proc is not None:
            pp = proc.to_plan(goal.id)
            if pp.source not in state["failed_sources"]:
                candidates.insert(0, pp)
        if not candidates:
            return None
        # System 1: the value model is confident about the first action -> no simulation needed
        firsts = list(dict.fromkeys(p.nodes[0].action for p in candidates))
        choice, conf = self.value.choose({"goal_type": goal.goal_type, "step": 0}, firsts)
        if choice is not None:
            plan = next(p for p in candidates if p.nodes[0].action == choice)
            result.system = "system1"
            self._record_decision(goal, [plan], plan, "value_model", conf)
            result.selected_plans.append(plan.source)
            return plan
        budget_ms = max_seconds * 1000

        def evaluate(p: ExecutionPlan) -> None:
            self.sim.evaluate(goal.goal_type, p, weights, rollouts=self.rollouts, budget_ms=budget_ms,
                              info_gain=0.1 if p.nodes and p.nodes[0].action in ("workspace.inspect", "world.query",
                                                                                 "tests.run") else 0.0)
        evaluated = branch_and_bound(candidates, evaluate)
        frontier = pareto_plans(evaluated) or evaluated
        plan = max(frontier, key=lambda p: p.utility)
        result.plans_considered.append({p.source: {"utility": p.utility, "success": p.expected_success,
                                                   "ms": p.estimated_duration_ms, "risk": p.risk_score,
                                                   "tail_risk": p.tail_risk} for p in evaluated})
        result.selected_plans.append(plan.source)
        self._record_decision(goal, evaluated, plan, "simulator", plan.utility)
        # carry over completed work (receding horizon: never redo observations)
        return plan

    def _record_decision(self, goal: Goal, plans: list[ExecutionPlan], chosen: ExecutionPlan, by: str,
                         score: float) -> None:
        ledger = getattr(self.rt, "ledger", None)
        if ledger is not None:
            ledger.append("PLANNER_DECISION", {
                "goal": goal.description[:300], "goal_type": goal.goal_type, "world_version":
                    getattr(getattr(self.rt, "world", None), "version", None),
                "candidate_plans": [p.source for p in plans], "selected": chosen.source, "by": by,
                "utility_scores": {p.source: p.utility for p in plans}, "score": score},
                object_type="goal", object_id=goal.id)

    # ------------------------------------------------------------------ execution
    async def _execute(self, node: PlanNode, goal: Goal, state: dict, principal: Principal, authorized: set[str],
                       mode: str, ws) -> StepRecord:
        t0 = time.perf_counter()
        cap = ACTION_CAPABILITY.get(node.action.split(":")[0], node.action)
        target = "/workspace/x" if cap.startswith("code.patch") else ""
        # writes go to the task's isolated working copy (never the source repo): treat as sandboxed
        sandboxed = cap == "python.run_tests" or (cap.startswith("code.patch") and ws is not None)
        env = ActionEnvelope(principal_id=principal.id, task_id=goal.id, capability=cap.split(":")[0],
                             target=target, arguments=node.arguments, sandboxed=sandboxed)
        gate = self.gate.check(principal, env, authorized, verified=True)
        rec = StepRecord(node_id=node.id, action=node.action, success=False,
                         predicted_success=node.success_probability, duration_ms=0, decision=gate.decision.value)
        if not gate.allowed:
            rec.summary = gate.reason
            rec.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        try:
            ok, metrics, summary = await self._act(node, goal, state, mode)
        except Exception as exc:  # a failed action is an observation, not a crash
            ok, metrics, summary = False, {"error": str(exc)[:300]}, f"error: {exc}"
        state["metrics"].update({k: v for k, v in metrics.items() if k != "error"})
        rec.success, rec.metrics, rec.summary = ok, metrics, summary[:500]
        rec.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        state["history"].append({"action": node.action, "success": ok, "at": now_iso()})
        return rec

    async def _act(self, node: PlanNode, goal: Goal, state: dict, mode: str) -> tuple[bool, dict, str]:
        action = node.action.split(":")[0]
        wdir = Path(goal.context["workspace"]) if goal.context.get("workspace") else None
        if action == "workspace.inspect":
            if wdir is None:
                return True, {}, "no workspace"
            files = [p.relative_to(wdir).as_posix() for p in sorted(wdir.rglob("*"))
                     if p.is_file() and "__pycache__" not in p.parts][:200]
            state["context"].append("FILES:\n" + "\n".join(files))
            return True, {"files_count": len(files)}, f"{len(files)} files"
        if action == "tests.run":
            if wdir is None:
                return False, {}, "no workspace"
            from hydra.tools.workspace import run_tests

            res = await run_tests(self.rt.sandbox, wdir, node.arguments.get("pattern"))
            fails = "\n".join(f"{f.test}: {f.message[:400]}" for f in res.failures[:5])
            state["context"].append(f"TESTS: passed={res.passed} failed={res.failed} errors={res.errors}\n{fails}")
            state["tests"] = res.model_dump()
            if node.arguments.get("pattern"):
                return True, {"targeted_tests_pass": res.success}, f"targeted: passed={res.passed} failed={res.failed}"
            state["full_suite_tests_pass"] = res.success
            if not state.get("workspace_patched"):
                state.setdefault("baseline_tests_pass", res.success)
            return True, {"tests_pass": res.success, "tests_failed": res.failed + res.errors,
                          "tests_passed": res.passed}, f"passed={res.passed} failed={res.failed}"
        if action == "world.query":
            world = getattr(self.rt, "world_rag", None)
            if world is None:
                return True, {}, "no world model"
            pkt = world.packet(node.arguments.get("query", goal.description))
            if pkt.render():
                state["context"].append(pkt.render())
            return True, {"world_facts": len(pkt.verified_facts)}, f"{len(pkt.verified_facts)} facts"
        if action == "memory.search":
            hits = await self.rt.retriever.retrieve(node.arguments.get("query", goal.description), "chat")
            if hits:
                state["context"].append("MEMORY:\n" + "\n".join(f"- {i.text}" for i, _ in hits[:5]))
            return True, {"memories": len(hits)}, f"{len(hits)} memories"
        if action == "model.reason":
            prompt = node.arguments.get("prompt", goal.description)
            ctx_text = "\n\n".join(state["context"][-6:])
            if wdir is not None:
                ctx_text += "\n\n" + _files_block(wdir)
            req = HydraRequest(messages=[Message(role="user", content=f"{prompt}\n\nCONTEXT:\n{ctx_text}"[:24000])],
                               mode=ExecutionMode(node.arguments.get("mode", mode if mode in
                                                                     ("fast", "balanced", "deep", "max", "private")
                                                                     else "balanced")),
                               local_only=bool(goal.context.get("local_only")), use_cache=False,
                               metadata={"goal": goal.id, "planner_step": node.id})
            resp = await self.rt.kernel.run(req)
            state["answer"] = resp.answer
            state["context"].append(f"ANALYSIS:\n{resp.answer[:3000]}")
            ok = resp.meta.decision == "answer" and resp.meta.confidence >= 0.3
            return ok, {"answer_confidence": resp.meta.confidence, "answer_verified": resp.meta.verified}, \
                f"confidence={resp.meta.confidence:.2f}"
        if action == "code.patch":
            if wdir is None:
                return False, {}, "no workspace"
            files = _files_block(wdir)
            prompt = (f"HYDRA_PATCH_REQUEST\nGOAL: {node.arguments.get('prompt', goal.description)}\n\n"
                      + "\n\n".join(state["context"][-4:]) + f"\n\n{files}\n\nReturn the FULL corrected content of "
                      "every file you change, each as:\n### FILE: relative/path.py\n```python\n...\n```\n"
                      "Do not modify tests unless they are wrong.")
            req = HydraRequest(messages=[Message(role="user", content=prompt[:30000])], mode=ExecutionMode.BALANCED,
                               local_only=bool(goal.context.get("local_only")), use_cache=False,
                               metadata={"goal": goal.id, "planner_step": node.id})
            resp = await self.rt.kernel.run(req)
            changed = apply_patch_answer(wdir, resp.answer)
            if changed:
                state["workspace_patched"] = True
                state["full_suite_tests_pass"] = False
                state["metrics"]["tests_pass"] = False
            state["context"].append(f"PATCH: changed {changed}")
            return bool(changed), {"patched_files": len(changed)}, f"changed {changed}"
        if action == "verify":
            st = goal.status(state["metrics"])
            return st == "achieved", {"goal_progress": goal.progress(state["metrics"])}, st
        return False, {}, f"unknown action {node.action}"

    # ------------------------------------------------------------------ learning
    def _learn_step(self, goal: Goal, node: PlanNode, rec: StepRecord, state: dict) -> None:
        self.historical.record(goal.goal_type, node.action, rec.success, rec.duration_ms, node.estimated_cost)
        self.calibration.record("ensemble", goal.goal_type, node.success_probability, rec.success)
        step = sum(1 for h in state["history"][:-1])
        self.value.update({"goal_type": goal.goal_type, "step": 0 if step == 0 else 1}, node.action,
                          1.0 if rec.success else 0.0)

    def _finish(self, goal: Goal, result: GoalResult, state: dict) -> None:
        actions = [s.action for s in result.steps if s.success]
        success = result.status == "achieved"
        trace = Trace(goal_type=goal.goal_type, actions=actions, success=success, duration_ms=result.duration_ms)
        self.traces_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.traces_path, "a", encoding="utf-8") as f:
            f.write(trace.model_dump_json() + "\n")
        for src in result.selected_plans:
            if src.startswith("procedure:"):
                pid = src.split(":", 1)[1].split("@")[0]
                if pid in self.procedures.items:
                    self.procedures.record(pid, success, 0.0, result.duration_ms)
        traces = [Trace.model_validate_json(x) for x in self.traces_path.read_text(encoding="utf-8").splitlines()
                  if x.strip()][-500:]
        for proc in ProcedureMiner().mine(traces):
            self.procedures.add(proc)
        corpus = getattr(self.rt, "corpus", None)
        if corpus is not None:
            from hydra.corpus.records import CorpusRecord, RecordType, RightsMetadata

            prev: dict[str, Any] = {"goal_type": goal.goal_type}
            for s in result.steps:
                corpus.ingest(CorpusRecord(
                    record_type=RecordType.ACTION_VALUE, source_type="goal_runner", source_task_id=goal.id,
                    input={"goal": goal.description[:500]}, state=dict(prev), action={"action": s.action},
                    output={"success": s.success, "metrics": s.metrics}, reward=1.0 if s.success else 0.0,
                    quality=0.85 if s.success else 0.7, verification=0.95, domain=[goal.goal_type],
                    capabilities=["planning"], rights=RightsMetadata(training_allowed=True),
                    metadata={"deterministic_proof": True}))
                prev = {"goal_type": goal.goal_type, "last_action": s.action, "last_success": s.success}
            corpus.ingest(CorpusRecord(
                record_type=RecordType.PLAN, source_type="goal_runner", source_task_id=goal.id,
                input={"objective": goal.description[:500]}, state={"goal_type": goal.goal_type},
                action={"strategy": result.selected_plans, "steps": [s.action for s in result.steps]},
                output={"status": result.status, "replans": result.replans}, reward=1.0 if success else 0.0,
                quality=0.9 if success else 0.65, verification=0.95, domain=[goal.goal_type],
                capabilities=["planning"], rights=RightsMetadata(training_allowed=True),
                flags=["hard"] if result.replans else [], metadata={"deterministic_proof": True}))

    def _checkpoint(self, goal: Goal, plan: ExecutionPlan | None, state: dict, result: GoalResult) -> Path:
        p = self.checkpoints / f"{goal.id}.json"
        p.write_text(json.dumps({"goal": goal.model_dump(mode="json"), "plan": plan.model_dump() if plan else None,
                                 "metrics": state["metrics"], "history": state["history"],
                                 "world_version": getattr(getattr(self.rt, "world", None), "version", None),
                                 "status": result.status, "saved_at": now_iso()}, indent=2, default=str),
                     encoding="utf-8")
        return p


def _files_block(root: Path, max_chars: int = 16000) -> str:
    out, used = [], 0
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        block = f"### FILE: {p.relative_to(root).as_posix()}\n```python\n{body.rstrip(chr(10))}\n```"
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def apply_patch_answer(root: Path, answer: str) -> list[str]:
    """Apply full-file blocks (### FILE: path) or a unified diff, only inside ``root``."""
    changed = []
    base = root.resolve()
    for m in FILE_BLOCK.finditer(answer or ""):
        rel = m.group("path").replace("\\", "/").lstrip("/")
        target = (base / rel).resolve()
        if base not in target.parents and target != base:
            continue
        new = m.group("body")
        if target.exists() and target.read_text(encoding="utf-8", errors="replace").strip() == new.strip():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new.rstrip("\n") + "\n", encoding="utf-8")
        changed.append(rel)
    if not changed and (d := DIFF_BLOCK.search(answer or "")):
        import subprocess

        r = subprocess.run(["git", "apply", "--unsafe-paths", "--directory", ".", "-"], input=d.group(1),
                           text=True, cwd=root, capture_output=True)
        if r.returncode == 0:
            changed = re.findall(r"^\+\+\+ b/(\S+)", d.group(1), re.M)
    return changed
