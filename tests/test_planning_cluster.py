# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Planner/Simulator, procedures, value model, epistemic planning; cluster scheduler and fabric."""

from __future__ import annotations

import asyncio
import time

from hydra.cluster.fabric import Priority, WorkItem, WorkQueue, run_fabric_worker
from hydra.cluster.nodes import GPUDevice, HardwareNode, ModelResidency, NodeRegistry
from hydra.cluster.scheduler import (AdmissionController, GlobalScheduler, PrefixIndex, create_parallel_plan,
                                     estimate_work)
from hydra.planning.epistemic import ExperimentProposal, choose_experiment, expected_information_gain
from hydra.planning.goals import Condition, ExecutionPlan, Goal, PlanNode, PlanWeights
from hydra.planning.htn import decompose, infer_goal
from hydra.planning.procedures import ProcedureMiner, ProcedureStore, Trace, ValueModel
from hydra.planning.simulator import CalibrationEngine, SimulatorEnsemble, monte_carlo
from tests.conftest import default_models


def test_goal_conditions_and_dag():
    g = Goal(description="x", success_conditions=[Condition(metric="tests_pass", value=True),
                                                  Condition(metric="latency", operator="<", value=300)],
             failure_conditions=[Condition(metric="budget_exhausted", value=True)])
    assert g.status({}) == "open" and g.status({"tests_pass": True, "latency": 120}) == "achieved"
    assert g.status({"budget_exhausted": True}) == "failed"
    p = ExecutionPlan(goal_id=g.id, nodes=[PlanNode(id="A", action="a"), PlanNode(id="B", action="b", dependencies=["A"]),
                                          PlanNode(id="C", action="c", dependencies=["A"]),
                                          PlanNode(id="D", action="d", dependencies=["B", "C"])])
    assert not p.validate_dag() and [n.id for n in p.ready()] == ["A"]
    p.nodes[0].status = "done"
    assert {n.id for n in p.ready()} == {"B", "C"}  # parallel branch
    p.nodes.append(PlanNode(id="E", action="e", dependencies=["F"]))
    assert p.validate_dag()


def test_htn_simulation_and_calibration():
    goal = infer_goal("Encuentra y corrige el bug", {"workspace": "/tmp/x"})
    assert goal.goal_type == "debug"
    plans = decompose(goal)
    sim = SimulatorEnsemble()
    for p in plans:
        sim.evaluate(goal.goal_type, p, PlanWeights(), rollouts=200)
    assert all(0 <= p.expected_success <= 1 for p in plans)
    succ, _ = monte_carlo(plans[0], 300, seed=1)
    assert 0 < sum(succ) / len(succ) <= 1
    cal = CalibrationEngine()
    for i in range(40):
        cal.record("ensemble", "debug", 0.8, i % 5 < 3)  # actual 60% -> over-confident
    assert cal.bias("ensemble", "debug") < -0.1 and cal.adjust("ensemble", "debug", 0.8) < 0.7


def test_information_gain_picks_discriminating_experiment():
    prior = {"db": 0.46, "network": 0.38, "cpu": 0.16}
    inspect_db = ExperimentProposal(id="inspect-db", hypotheses=list(prior), cost=0.04, likelihoods={
        "db_waits_high": {"db": 0.9, "network": 0.1, "cpu": 0.1}, "db_waits_low": {"db": 0.1, "network": 0.9, "cpu": 0.9}})
    restart = ExperimentProposal(id="restart", hypotheses=list(prior), cost=0.1, risk=0.42, reversible=False,
                                 likelihoods={"better": {"db": 0.5, "network": 0.5, "cpu": 0.6},
                                              "same": {"db": 0.5, "network": 0.5, "cpu": 0.4}})
    ranked = choose_experiment(prior, [restart, inspect_db])
    assert ranked[0].id == "inspect-db" and ranked[0].information_gain > 0.4
    assert expected_information_gain(prior, restart.likelihoods) < 0.05


def test_procedure_mining_versioning_and_value_model(tmp_path):
    traces = [Trace(goal_type="debug", actions=["workspace.inspect", "tests.run", "code.patch", "tests.run"], success=True)
              for _ in range(4)] + [Trace(goal_type="debug", actions=["code.patch"], success=False)]
    procs = ProcedureMiner(min_support=3).mine(traces)
    assert procs and procs[0].steps == ["workspace.inspect", "tests.run", "code.patch", "tests.run"]
    store = ProcedureStore(tmp_path / "p.json")
    p = store.add(procs[0])
    assert store.advance(p.id).status == "SHADOW"
    for _ in range(6):
        store.record(p.id, True, 0.0, 100)
    store.advance(p.id)
    assert store.advance(p.id).status == "ACTIVE" and store.best("debug").id == p.id
    vm = ValueModel(tmp_path / "v.json")
    for _ in range(6):
        vm.update({"goal_type": "debug", "step": 0}, "workspace.inspect", 1.0)
        vm.update({"goal_type": "debug", "step": 0}, "code.patch", 0.2)
    assert vm.choose({"goal_type": "debug", "step": 0}, ["code.patch", "workspace.inspect"])[0] == "workspace.inspect"


def test_verification_report_layers(tmp_path):
    from hydra.planning.runner import verification_report

    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "broken.py").write_text("def f(:\n")
    diff_ok = "--- a/ok.py\n+++ b/ok.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n"
    good = verification_report(diff_ok, tmp_path, baseline_failed=True, full_suite_passed=True)
    assert good["verified"] and good["syntax_passed"]
    no_red = verification_report(diff_ok, tmp_path, baseline_failed=False, full_suite_passed=True)
    assert not no_red["improvement_demonstrated"] and not no_red["verified"]
    diff_broken = diff_ok + "--- a/broken.py\n+++ b/broken.py\n@@ -1 +1 @@\n-x\n+def f(:\n"
    bad = verification_report(diff_broken, tmp_path, baseline_failed=True, full_suite_passed=True)
    assert not bad["syntax_passed"] and "broken.py" in bad["syntax_errors"] and not bad["verified"]


async def test_goal_runner_fixes_repository(runtime, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    res = await runtime.goals.run("Encuentra y corrige el bug del repositorio", workspace=repo)
    assert res.status == "achieved" and res.metrics["tests_pass"] is True
    verification = res.metrics["verification"]  # HYDRA-SO layered criteria
    assert verification["baseline_failed"] and verification["improvement_demonstrated"]
    assert verification["changed_python"] == ["calc.py"] and verification["verified"]
    assert "+    return a + b" in res.patch and (repo / "calc.py").read_text().count("a - b") == 1  # source untouched
    assert any(e.event_type == "PLANNER_DECISION" for e in runtime.ledger.events())
    assert runtime.corpus.search(record_type="action_value")


def test_scheduler_prefers_resident_model_and_respects_sla():
    reg = NodeRegistry()
    models = default_models()
    reg.heartbeat(HardwareNode(id="gpu-a", gpus=[GPUDevice(id="GPU0", total_vram_gb=24, free_vram_gb=6)],
                               residency=[ModelResidency(model_id="medium", node_id="gpu-a", tier="HOT")]))
    sch = GlobalScheduler(reg)
    q = {"small": 0.62, "medium": 0.85, "large": 0.9, "cloud": 0.95}
    order = [m.id for m in sch.rerank(models[:3], quality_of=lambda m: q[m.id], mode="fast", private=True)]
    assert order[0] == "medium"  # loaded + good enough beats the unloaded larger model in FAST mode
    placements = sch.place(models, quality_of=lambda m: q[m.id], private=True, mode="balanced")
    assert all(p.model_id != "cloud" for p in placements)
    adm = AdmissionController()
    node = reg.nodes["gpu-a"]
    assert adm.reserve(node, 5.0) is not None and adm.reserve(node, 5.0) is None  # capacity reserved
    assert create_parallel_plan(40, False, 4, 24).tensor_parallel == 2
    assert estimate_work(8000, 500).expected_decode_ms > estimate_work(8000, 50).expected_decode_ms
    idx = PrefixIndex()
    fps = PrefixIndex.fingerprints("system prompt", "memory pack")
    idx.record(fps, "gpu-a", "conv-1")
    assert idx.locality(fps, "gpu-a") == 1.0 and idx.affinity_node("conv-1") == "gpu-a"


async def test_fabric_leases_idempotency_priority(tmp_path):
    q = WorkQueue(tmp_path / "q.db")
    q.submit(WorkItem(capability="inference", priority=Priority.BACKGROUND_LAB, idempotency_key="lab"))
    q.submit(WorkItem(capability="inference", priority=Priority.INTERACTIVE, idempotency_key="user"))
    first = q.claim(["inference"], "w1", lease_s=0.2)
    assert first.priority == Priority.INTERACTIVE
    time.sleep(0.3)
    again = q.claim(["inference"], "w2", lease_s=5)
    assert again.id == first.id and again.attempts == 2  # expired lease -> re-delivered
    q.complete(again.id, "w2", {"answer": 42})
    assert q.submit(WorkItem(capability="inference", idempotency_key="user")).result == {"answer": 42}

    async def handler(item):
        return {"ok": True}
    assert await run_fabric_worker(q, ["inference"], handler, once=True) == 1
    q.checkpoint("long-task", 2, {"step": "two"})
    assert q.last_checkpoint("long-task") == (2, {"step": "two"})
    await asyncio.sleep(0)


async def test_run_tests_reports_collection_errors(tmp_path):
    from hydra.tools.sandbox import SubprocessSandbox
    from hydra.tools.workspace import run_tests

    (tmp_path / "test_broken.py").write_text("def test_x(:\n    pass\n")
    res = await run_tests(SubprocessSandbox(), tmp_path)
    assert not res.success and res.errors >= 1
