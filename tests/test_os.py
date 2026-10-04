# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA OS subsystems: policy, cache, metacognition, uncertainty, provenance, artifacts,
world state, perception, compression, simulation, failure memory, learned router,
counterfactuals, research graph, evals, model compiler, runtime monitor, lab."""

from uuid import UUID, uuid4

import pytest

from hydra.artifacts.engine import ArtifactEngine, ArtifactType
from hydra.bus.memory import InMemoryEventBus
from hydra.core.contracts import (
    ExecutionMode,
    HydraRequest,
    Message,
    ModelRequest,
    ModelResponse,
    RoutingDecision,
    TaskType,
)
from hydra.core.errors import ErrorKind
from hydra.core.events import EventType, HydraEvent
from hydra.evals.engine import apply_to_registry
from hydra.evals.suites import solid_png
from hydra.lab.lab import ExperimentStatus, Gates
from hydra.memory.compression import compress, expand
from hydra.memory.failures import FailureMemory
from hydra.policy.kernel import PolicyKernel, Sensitivity
from hydra.providers.adapter import ModelCompiler, extract_json
from hydra.registry.models import ModelQuirks
from hydra.registry.runtime_monitor import load_from_metrics, parse_prometheus
from hydra.router.learned import ABRouter, LearnedRoutingPolicy
from hydra.simulation.engine import Simulator
from hydra.telemetry.metrics import InferenceRun
from hydra.tools.builtin import register_builtin_tools
from hydra.tools.definitions import ToolCall, ToolContext, WorkerCapabilities
from hydra.tools.executor import ToolExecutor
from hydra.tools.policy import ToolPolicyEngine
from hydra.tools.registry import ToolRegistry
from hydra.tools.sandbox import SubprocessSandbox
from hydra.verification.uncertainty import apply_verdict, assess_claims, segment_claims
from hydra.world.state import WorldState

from .conftest import default_models, model


def req(text: str, **kw) -> HydraRequest:
    return HydraRequest(messages=[Message(role="user", content=text)], **kw)


async def events_of(runtime, task_id: str) -> list[HydraEvent]:
    return await runtime.bus.history(UUID(task_id))


# ------------------------------------------------------------------ policy kernel
def test_policy_classification_and_redaction():
    pk = PolicyKernel()
    level, findings = pk.classify("mi clave es sk-abcdefghijklmnopqrstuvwxyz123456 y postgres://u:p4ss@db/x")
    assert level == Sensitivity.SECRET and {f.kind for f in findings} >= {"api_key", "connection_string"}
    assert "sk-abc" not in pk.redact("token sk-abcdefghijklmnopqrstuvwxyz123456")
    assert pk.classify("email ana@example.com")[0] == Sensitivity.CONFIDENTIAL
    assert pk.classify("hola mundo")[0] == Sensitivity.PUBLIC
    assert not pk.model_allowed("cloud", local=False, sensitivity=Sensitivity.CONFIDENTIAL)
    assert pk.model_allowed("small", local=True, sensitivity=Sensitivity.SECRET)


async def test_secrets_never_reach_cloud_and_are_redacted(runtime, mock):
    r = await runtime.kernel.run(req("Analiza en profundidad este error, password: hunter2secret",
                                     mode=ExecutionMode.DEEP))
    assert r.meta.sensitivity == "secret"
    assert "cloud" not in {m for m, _ in mock.calls}
    created = (await events_of(runtime, r.meta.task_id))[0]
    assert "hunter2secret" not in created.payload["objective"]
    task = await runtime.telemetry.get_task(UUID(r.meta.task_id))
    assert "hunter2secret" not in str(task.request)


async def test_forbidden_request_is_refused_without_models(runtime, mock):
    r = await runtime.kernel.run(req("Explícame cómo enriquecer uranio en casa"))
    assert r.meta.decision == "refuse" and mock.calls == []


async def test_tool_needing_confirmation_is_reported(tmp_path):
    bus = InMemoryEventBus()
    reg = register_builtin_tools(ToolRegistry(), SubprocessSandbox())
    ex = ToolExecutor(reg, ToolPolicyEngine(PolicyKernel()), bus)
    ctx = ToolContext(task_id=uuid4(), workspace=tmp_path,
                      capabilities=WorkerCapabilities(tools={"git.apply_patch"}, filesystem_paths=["."]))
    r = await ex.execute(ToolCall(name="git.apply_patch", arguments={"patch": "x"}), ctx)
    assert not r.success and "confirmation" in r.error
    ev = (await bus.history(ctx.task_id))[-1]
    assert ev.type == EventType.TOOL_DENIED and ev.payload["kind"] == "needs_confirmation"


# ------------------------------------------------------------------ semantic cache
async def test_semantic_cache_skips_inference(runtime, mock):
    first = await runtime.kernel.run(req(CODE_TASK))
    assert first.meta.verified and not first.meta.cached
    calls = len(mock.calls)
    again = await runtime.kernel.run(req(CODE_TASK.upper().replace("\n", "  \n")))
    assert again.meta.cached and len(mock.calls) == calls
    assert again.meta.task_id != first.meta.task_id
    miss = await runtime.kernel.run(req(CODE_TASK, use_cache=False))
    assert not miss.meta.cached


CODE_TASK = "Revisa esta función Python:\n```python\ndef doble(x):\n    return x * 2\nprint(doble(21))\n```"


# ------------------------------------------------------------------ metacognition
async def test_ambiguous_request_asks_instead_of_guessing(runtime, mock):
    r = await runtime.kernel.run(req("arréglalo"))
    assert r.meta.decision == "ask" and "?" in r.answer and mock.calls == []


# ------------------------------------------------------------------ uncertainty router
def test_claims_segmentation_and_assessment():
    answer = "La capital de Francia es París. El puerto por defecto es 8080.\n```python\nprint(1)\n```"
    claims = segment_claims(answer)
    assert any(c.id.startswith("code") for c in claims) and len(claims) == 3
    claims = assess_claims(claims, 0.8, ["La capital de Francia es París."], ["port 9090"],
                           ["el puerto por defecto es incorrecto"])
    by_text = {c.text: c for c in claims if not c.id.startswith("code")}
    assert by_text["La capital de Francia es París."].status == "supported"
    assert by_text["El puerto por defecto es 8080."].status == "uncertain"
    refuted = apply_verdict(by_text["El puerto por defecto es 8080."], {"verdict": "refuted", "correction": "9090"})
    assert refuted.status == "refuted" and refuted.correction == "9090"


async def test_response_carries_claims_provenance_and_artifacts(runtime):
    r = await runtime.kernel.run(req(CODE_TASK))
    assert r.claims and all(0 <= c.confidence <= 1 for c in r.claims)
    types = {a["type"] for a in r.artifacts}
    assert {"answer", "execution_plan"} <= types
    ev = await events_of(runtime, r.meta.task_id)
    prov = next(e for e in ev if e.type == EventType.PROVENANCE_RECORDED).payload["records"]
    sources = {s["type"] for rec in prov for s in rec["sources"]}
    assert "tool_result" in sources and "model" in sources


def test_artifact_engine_types():
    answer = ("Parche:\n```diff\n--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n```\n"
              "```json\n[{\"a\": 1}, {\"a\": 2}]\n```\n```python\nprint(2)\n```")
    arts = ArtifactEngine().extract(answer, plan={"strategy": "cascade"}, images=[solid_png((0, 0, 0))])
    types = [a.type for a in arts]
    assert ArtifactType.CODE_PATCH in types and ArtifactType.DATASET in types and ArtifactType.CODE in types
    assert ArtifactType.EXECUTION_PLAN in types and ArtifactType.IMAGE in types
    patch = next(a for a in arts if a.type == ArtifactType.CODE_PATCH)
    assert patch.metadata["files"] == ["x.py"]


# ------------------------------------------------------------------ world state + perception
def test_world_state_updates_and_conflicts():
    w = WorldState()
    w.from_text("HydraAPI depends on Redis. service api listens on port 8080")
    w.from_perception({"objects": [{"name": "button", "attributes": {"color": "blue"}}],
                       "relations": [{"subject": "button", "predicate": "below", "object": "panel"}],
                       "text": ["Error 500"], "description": "a settings screen"}, "vision:m")
    w.from_perception({"objects": [{"name": "button", "attributes": {"color": "red"}}]}, "vision:m2")
    assert {"hydraapi", "redis", "button", "panel"} <= set(w.objects)
    assert any("button.color" in u for u in w.uncertainty)
    assert "Error 500" in w.render()


async def test_multimodal_perception_updates_world(runtime):
    runtime.registry.add(model("vlm", tier=2, vision=0.9, tools=0.4))
    r = await runtime.kernel.run(HydraRequest(messages=[Message(
        role="user", content="¿De qué color es la imagen?", images=[solid_png((220, 20, 20))])]))
    assert "red" in r.answer.lower()
    ev = await events_of(runtime, r.meta.task_id)
    world = [e for e in ev if e.type == EventType.WORLD_UPDATED][-1].payload["world"]
    assert world["objects"]["square"]["attributes"]["color"] == "red"
    assert "vlm" in {m for m, role in runtime.providers["mock"].calls if role == "vision"}
    assert any(a["type"] == "image" for a in r.artifacts)


# ------------------------------------------------------------------ context compression
def test_context_compression_keeps_pointers():
    msgs = [{"role": "user", "content": f"Mensaje {i}. Decidimos usar PostgreSQL 16. ¿Migramos el esquema {i}? "
                                        + "relleno " * 200} for i in range(12)]
    state, recent = compress(msgs, keep_last=2, budget_tokens=500)
    assert state is not None and len(recent) == 2 and state.compressed_messages == 10
    assert state.decisions and state.open_questions
    item = state.decisions[0]
    assert "PostgreSQL" in expand(msgs, item.pointer)
    assert state.compressed_tokens < state.original_tokens


async def test_kernel_compresses_long_conversations(runtime):
    msgs = [Message(role="user" if i % 2 == 0 else "assistant",
                    content=f"Turno {i}: el servicio api usa puerto {8000 + i}. " + "detalle " * 600)
            for i in range(30)]
    r = await runtime.kernel.run(HydraRequest(messages=msgs + [Message(role="user", content="¿Cuánto es 2+2?")]))
    ev = await events_of(runtime, r.meta.task_id)
    assert any(e.type == EventType.CONTEXT_COMPRESSED for e in ev)


# ------------------------------------------------------------------ simulation
async def test_simulation_predicts_and_blocks(tmp_path):
    sim = Simulator()
    reg = register_builtin_tools(ToolRegistry(), SubprocessSandbox())
    ctx = ToolContext(task_id=uuid4(), workspace=tmp_path,
                      capabilities=WorkerCapabilities(tools={"filesystem.write", "python.execute", "git.apply_patch"},
                                                      filesystem_paths=["."]), approved={"git.apply_patch"})
    (tmp_path / "a.txt").write_text("uno\ndos\ntres\n")
    r = await sim.simulate(ToolCall(name="filesystem.write", arguments={"path": "a.txt", "content": "uno\n"}),
                           reg.get("filesystem.write").definition, ctx)
    assert r.ok and not r.reversible and "-2" in r.summary
    r = await sim.simulate(ToolCall(name="python.execute", arguments={"code": "import os\nos.remove('x')"}),
                           reg.get("python.execute").definition, ctx)
    assert "os" in r.summary and r.risk > 0.2
    ranked = await sim.compare([
        (ToolCall(name="python.execute", arguments={"code": "import shutil; shutil.rmtree('/')"}),
         reg.get("python.execute").definition),
        (ToolCall(name="python.execute", arguments={"code": "print(1+1)"}), reg.get("python.execute").definition),
    ], ctx)
    assert ranked[0][0].arguments["code"] == "print(1+1)"

    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ex = ToolExecutor(reg, ToolPolicyEngine(PolicyKernel()), InMemoryEventBus(), simulator=sim)
    bad = await ex.execute(ToolCall(name="git.apply_patch", arguments={"patch": "--- a/zz\n+++ b/zz\n@@ -1 +1 @@\n-x\n+y\n"}),
                           ctx)
    assert not bad.success and "simulation rejected" in bad.error


# ------------------------------------------------------------------ failure memory
async def test_failure_memory_learns_patterns():
    fm = FailureMemory(min_observations=3)
    tid = uuid4()
    for _ in range(4):
        await fm.observe(HydraEvent(task_id=tid, type=EventType.MODEL_FAILED, source="r",
                                    payload={"model": "m", "kind": "invalid_json", "ctx_bucket": 80000,
                                             "structured": True}))
    await fm.observe(HydraEvent(task_id=tid, type=EventType.MODEL_COMPLETED, source="r",
                                payload={"model": "m", "ctx_bucket": 4000, "structured": False}))
    assert fm.should_avoid("m", {"ctx_bucket": 80000})
    assert not fm.should_avoid("m", {"ctx_bucket": 4000})
    assert fm.report()[0]["kind"] == "invalid_json"


# ------------------------------------------------------------------ learned router + A/B
def test_learned_router_and_ab():
    models = default_models()
    runs = []
    for i in range(30):
        tid = uuid4()
        runs.append(InferenceRun(task_id=tid, task_type="coding", model_id="small", role="coder",
                                 latency_ms=100, verifier_score=0.95, complexity=0.2, mode="balanced", arm="learned"))
        runs.append(InferenceRun(task_id=uuid4(), task_type="coding", model_id="large", role="coder",
                                 latency_ms=3000, verifier_score=0.5, complexity=0.2, mode="balanced", arm="heuristic"))
    policy = LearnedRoutingPolicy(min_samples=20)
    assert policy.fit(runs) == 60 and policy.ready()
    route = RoutingDecision(task_type=TaskType.CODING, complexity=0.2, risk=0.1)
    assert policy.rank(models, route, req("x"))[0].id == "small"
    ab = ABRouter(policy, learned_fraction=0.5)
    arms = {ab.arm_for(uuid4()) for _ in range(50)}
    assert arms == {"learned", "heuristic"}
    report = {a.arm: a for a in ABRouter.report(runs)}
    assert report["learned"].mean_quality > report["heuristic"].mean_quality


# ------------------------------------------------------------------ counterfactuals
async def test_counterfactual_detects_unnecessary_ensemble(runtime):
    r = await runtime.kernel.run(req("Demuestra y razona: ¿cuánto es 12 * 12?", mode=ExecutionMode.DEEP))
    ev = await events_of(runtime, r.meta.task_id)
    cf = next(e for e in ev if e.type == EventType.COUNTERFACTUAL_ANALYZED).payload
    assert cf["ensemble_size"] >= 2 and cf["ensemble_necessary"] is False
    ensemble = [e.payload["model"] for e in ev if e.type == EventType.ANSWER_PROPOSED]
    chosen = next(e for e in ev if e.type == EventType.VERIFICATION_COMPLETED).payload["target"].split(":")[1]
    tiers = {m: runtime.registry.get(m).tier for m in ensemble}
    has_cheaper = tiers[chosen] > min(tiers.values())
    assert (cf["cheaper_alternative"] is not None) == has_cheaper
    assert runtime.kernel.counterfactual_stats.summary()["unnecessary_ensembles"] >= 1


# ------------------------------------------------------------------ research graph
async def test_research_graph(runtime):
    r = await runtime.kernel.run(req("Investiga el estado del arte de la cuantización GGUF; compara Q4_K_M y "
                                     "Q5_K_M y además resume sus ventajas en CPU", mode=ExecutionMode.DEEP))
    ev = await events_of(runtime, r.meta.task_id)
    graph = next(e for e in ev if e.type == EventType.RESEARCH_GRAPH_UPDATED).payload
    kinds = [n["kind"] for n in graph["nodes"]]
    assert kinds.count("subquestion") >= 2 and kinds.count("answer") >= 2
    assert any(a["type"] == "research_graph" for a in r.artifacts)
    assert any(a["type"] == "report" for a in r.artifacts)


# ------------------------------------------------------------------ model compiler
def test_model_compiler_prompted_json_and_tools():
    prof = model("weird", quirks=ModelQuirks(native_json_schema=False, native_tools=False, system_role=False))
    mc = ModelCompiler()
    req_ = ModelRequest(messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
                        response_schema={"type": "object"},
                        tools=[{"type": "function", "function": {"name": "python__execute", "parameters": {}}}])
    c = mc.compile(prof, req_)
    assert c.response_schema is None and c.tools is None
    assert c.messages[0]["role"] == "user" and "JSON" in c.messages[0]["content"]
    out = mc.decompile(c, ModelResponse(model_id="weird", content='Sure! ```json\n{"a": 1}\n```', latency_ms=1))
    assert out.structured == {"a": 1}
    c2 = mc.compile(prof, req_.model_copy(update={"response_schema": None}))
    out = mc.decompile(c2, ModelResponse(model_id="weird", latency_ms=1,
                                         content='{"tool_call": {"name": "python__execute", "arguments": {"code": "1"}}}'))
    assert out.tool_calls[0]["arguments"] == {"code": "1"}
    assert extract_json('prefix {"x": [1, {"y": "}"}]} suffix') == {"x": [1, {"y": "}"}]}


def test_textual_tool_calls_from_local_models():
    """qwen2.5-coder on Ollama writes tool calls as JSON text instead of native tool_calls."""
    native = model("coder")  # claims native tools
    tools = [{"type": "function", "function": {"name": "python__execute", "parameters": {}}}]
    req_ = ModelCompiler().compile(native, ModelRequest(messages=[{"role": "user", "content": "x"}], tools=tools))
    text = ('```json\n{"name": "python__execute", "arguments": {"code": "print(1)"}}\n```\n'
            "La función está mal...")
    out = ModelCompiler().decompile(req_, ModelResponse(model_id="coder", content=text, latency_ms=1))
    assert out.tool_calls == [{"id": None, "name": "python__execute", "arguments": {"code": "print(1)"}}]
    assert out.content == ""
    other = ModelCompiler().decompile(req_, ModelResponse(
        model_id="coder", latency_ms=1, content='Ejemplo: {"name": "Ana", "arguments": {}}'))
    assert other.tool_calls == []  # not an offered tool: left as text


# ------------------------------------------------------------------ runtime monitor
def test_prometheus_parsing_and_load():
    text = """# HELP x
vllm:num_requests_running{model="a"} 4
vllm:num_requests_waiting{model="a"} 12
vllm:kv_cache_usage_perc{model="a"} 0.9
"""
    load = load_from_metrics(parse_prometheus(text))
    assert load.waiting == 12 and load.load > 0.7
    m = model("busy")
    m.queue_depth = 8
    assert m.predicted_latency_ms == pytest.approx(m.estimated_latency_ms * 3)


# ------------------------------------------------------------------ eval engine
async def test_eval_engine_profiles_a_model(runtime):
    report = await runtime.evaluator.run_model(runtime.registry.get("medium"),
                                               ["coding", "reasoning", "structured", "tool_use", "hallucination"])
    cases = {c.id: c for c in report.cases}
    assert cases["code.is_prime"].passed and cases["code.reverse_words"].passed  # real tests in the sandbox
    assert not cases["code.flatten"].passed  # the offline model has no solution: graded honestly
    assert cases["reason.mult"].passed
    assert report.suites["tool_use"].score == 1.0
    prof = apply_to_registry(report, runtime.registry)
    assert prof.runs["coding"] >= 25 and prof.learned_quality["coding"] == report.suites["coding"].score


# ------------------------------------------------------------------ HYDRA Lab
async def test_lab_shadow_canary_promotion(runtime):
    lab = runtime.lab
    # Offline latencies are a few ms, so a +25% latency gate would make this flow test flaky.
    exp = lab.create("stricter acceptance", "policy", {"accept_confidence": 0.7},
                     gates=Gates(shadow_samples=3, canary_samples=3, latency_increase=100.0))
    exp = await lab.run_benchmark(exp.id, ["reasoning"])
    assert exp.status == ExperimentStatus.SHADOW
    for i in range(4):
        await lab.serve(req(f"¿Cuánto es {i} + 5?", use_cache=False))
    await lab.drain()
    assert lab.experiments[exp.id].status == ExperimentStatus.CANARY
    fractions = set()
    for i in range(600):  # 5% -> 20% -> 100% of traffic
        e = lab.experiments[exp.id]
        if e.status == ExperimentStatus.CANARY:
            fractions.add(e.canary_fraction)
        await lab.serve(req(f"¿Cuánto es {i} * 3?", use_cache=False), task_id=uuid4())
        if lab.experiments[exp.id].status == ExperimentStatus.PROMOTED:
            break
    assert lab.experiments[exp.id].status == ExperimentStatus.PROMOTED
    assert fractions == {0.05, 0.20, 1.0}
    assert runtime.kernel.config.accept_confidence == 0.7


async def test_lab_rejects_degrading_candidate(runtime):
    lab = runtime.lab
    exp = lab.create("broken router", "router", {"disabled_models": ["small", "medium", "large", "cloud"]},
                     gates=Gates(shadow_samples=3))
    lab.start_shadow(exp.id)
    for i in range(4):
        await lab.serve(req(f"¿Cuánto es {i} + 1?", use_cache=False))
    await lab.drain()
    assert lab.experiments[exp.id].status == ExperimentStatus.REJECTED
    assert runtime.kernel.config.disabled_models == set()  # production untouched


async def test_shadow_runs_have_no_side_effects(runtime, tmp_path):
    before_tasks = len(runtime.telemetry.tasks)
    before_mem = len(await runtime.memory.all())
    await runtime.kernel.run(req("Recuerda que el servicio billing usa puerto 7777"), shadow=True)
    assert len(runtime.telemetry.tasks) == before_tasks
    assert len(await runtime.memory.all()) == before_mem


async def test_failure_memory_steers_ranking(runtime, mock):
    mock.fail["small"] = ErrorKind.INVALID_JSON
    for _ in range(4):
        try:
            await runtime.kernel.run(req("¿Cuánto es 3+3?", use_cache=False))
        except Exception:
            pass
    mock.fail.clear()
    calls_before = len(mock.calls)
    await runtime.kernel.run(req("¿Cuánto es 4+4?", use_cache=False))
    assert "small" not in [m for m, _ in mock.calls[calls_before:]]
