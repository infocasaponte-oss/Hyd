# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.blackboard.projector import replay
from hydra.blackboard.state import BlackboardState
from hydra.core.contracts import HydraRequest, Message, RoutingDecision, TaskType
from hydra.core.events import EventType, HydraEvent
from hydra.memory.compiler import MemoryCompiler, OutcomeRecord, extract_facts
from hydra.memory.context import ContextBudget, ContextCompiler
from hydra.memory.embeddings import HashingEmbedder, cosine
from hydra.memory.graph import MemoryGraph
from hydra.memory.models import MemoryStatus, MemoryType
from hydra.memory.retriever import MemoryRetriever
from hydra.memory.store import InMemoryMemoryStore
from hydra.verification.confidence import ConfidenceInputs, confidence_score
from hydra.verification.consensus import agreement
from hydra.verification.verifier import Verifier


def outcome(objective: str, **kw) -> OutcomeRecord:
    base = dict(task_type="chat", objective=objective, answer="ok", success=True, verified=False,
                confidence=0.8, complexity=0.2, strategy=["cascade"], tools=[])
    return OutcomeRecord(**{**base, **kw})


def test_fact_extraction():
    facts = extract_facts("el servicio payments usa puerto 9123 y HydraAPI depends on Redis. hydra uses postgresql")
    triples = {(f.subject, f.predicate, f.object) for f in facts}
    assert ("payments", "listens_on", "9123") in triples
    assert ("HydraAPI", "depends_on", "Redis") in triples
    assert ("hydra", "uses", "postgresql") in triples
    assert not any(f.predicate == "uses" and f.object == "puerto" for f in facts)


@pytest.fixture
def mem():
    store = InMemoryMemoryStore()
    emb = HashingEmbedder()
    return store, MemoryCompiler(store, emb), MemoryRetriever(store, emb)


async def test_compiler_keeps_useful_drops_trivial(mem):
    store, compiler, _ = mem
    await compiler.compile(outcome("¿Cuánto es 2+2?"))
    assert await store.all() == []  # trivial: nothing worth remembering
    stored = await compiler.compile(outcome("Recuerda: el servicio payments usa puerto 9123"))
    assert any(m.memory_type == MemoryType.SEMANTIC and m.content["object"] == "9123" for m in stored)
    assert all(m.importance >= 0.7 for m in stored)


async def test_dedupe_and_conflicts(mem):
    store, compiler, _ = mem
    await compiler.compile(outcome("service api listens on port 8080"))
    await compiler.compile(outcome("service api listens on port 8080"))
    facts = await store.all(MemoryType.SEMANTIC)
    assert len(facts) == 1 and facts[0].content["source_count"] == 2

    await compiler.compile(outcome("service api listens on port 8081"))
    facts = {f.content["object"]: f for f in await store.all(MemoryType.SEMANTIC)}
    assert facts["8080"].status == MemoryStatus.CONFLICT and facts["8081"].status == MemoryStatus.CONFLICT
    assert facts["8081"].id in facts["8080"].conflicts_with

    winner = await compiler.resolve_conflict(facts["8081"].id)
    assert winner.status == MemoryStatus.VERIFIED
    assert (await store.get(facts["8080"].id)).content["valid_until"]


async def test_retriever_and_graph(mem):
    store, compiler, retriever = mem
    await compiler.compile(outcome("HydraAPI depends on Redis. Worker depends on Redis. hydra uses postgresql"))
    ranked = await retriever.retrieve("¿qué servicios dependen de Redis?", "chat")
    assert any("Redis" in i.text for i, _ in ranked)
    g = MemoryGraph.build(await store.all(MemoryType.SEMANTIC))
    assert sorted(g.dependents("redis")) == ["HydraAPI", "Worker"]


async def test_procedural_memory_merges(mem):
    store, compiler, _ = mem
    kw = dict(task_type="coding", tools=["python.execute"], strategy=["cascade", "tool:python.execute"],
              confidence=0.9, complexity=0.5)
    await compiler.compile(outcome("debug a", **kw))
    await compiler.compile(outcome("debug b", **{**kw, "success": False}))
    procs = await store.all(MemoryType.PROCEDURAL)
    assert len(procs) == 1 and procs[0].content["runs"] == 2 and procs[0].content["success_rate"] == 0.5


def test_embedder_similarity():
    import asyncio
    a, b, c = asyncio.run(HashingEmbedder().embed(["redis connection pool", "pool of redis connections", "banana"]))
    assert cosine(a, b) > cosine(a, c)


def test_context_compiler_respects_budget():
    budget = ContextBudget.for_window(4096, 512)
    msgs = ContextCompiler().compile(budget, "sys", [{"role": "user", "content": "x" * 100_000}],
                                     memories=["m" * 50_000, "short memory"])
    assert sum(len(m["content"]) for m in msgs) < 4096 * 4


def test_confidence_engine():
    c = confidence_score(ConfidenceInputs(agreement=0.92, verification=0.95, evidence=0.80,
                                          historical_accuracy=0.91))
    assert 0.8 < c < 0.95
    assert confidence_score(ConfidenceInputs()) == 0.5
    assert agreement(["x = 391", "the result is 391"]) == 1.0


def test_verifier_layers():
    req = HydraRequest(messages=[Message(role="user", content="python code please")])
    route = RoutingDecision(task_type=TaskType.CODING, complexity=0.5, risk=0.1)
    state = BlackboardState()
    bad = Verifier().verify(req, route, state, "```python\ndef f(:\n```")
    assert not bad.passed
    state.tool_results.append({"tool": "python.execute", "success": True, "requested_by": "coder:m"})
    state.critiques.append({"target": "c1", "verdict": "pass", "score": 0.9, "issues": []})
    good = Verifier().verify(req, route, state, "```python\nprint(1)\n```", claim_id="c1", model_id="m")
    assert good.passed and good.verified and good.tool_validation == 1.0


def test_successful_web_tool_does_not_verify_answer():
    req = HydraRequest(messages=[Message(role="user", content="busca teoremas en internet")])
    route = RoutingDecision(task_type=TaskType.RESEARCH, complexity=0.5, risk=0.1)
    state = BlackboardState()
    state.tool_results.append({"tool": "web.search", "success": True})
    result = Verifier().verify(req, route, state, "Abre tu navegador y busca teoremas.")
    assert result.tool_validation == 1.0
    assert not result.verified
    assert not result.independent


def test_replay_rebuilds_state():
    tid = uuid4()
    events = [
        HydraEvent(task_id=tid, type=EventType.TASK_CREATED, source="k", payload={"objective": "o"}),
        HydraEvent(task_id=tid, type=EventType.ANSWER_PROPOSED, source="r", payload={"model": "m", "answer": "a"}),
        HydraEvent(task_id=tid, type=EventType.TOOL_COMPLETED, source="t", payload={"tool": "python.execute"}),
        HydraEvent(task_id=tid, type=EventType.SYNTHESIS_COMPLETED, source="s", payload={"answer": "final"}),
    ]
    s = replay(events)
    assert s.objective == "o" and s.models_used == ["m"] and s.tools_used == ["python.execute"]
    assert s.final_answer == "final"
