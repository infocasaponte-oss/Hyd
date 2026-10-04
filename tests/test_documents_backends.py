# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F3e: the small registries of the engine and the factory on shared documents (files or PostgreSQL).

PostgreSQL cases need HYDRA_IT_POSTGRES (``pg_url`` in conftest gives each test its own database)."""
from __future__ import annotations

import json
import threading
from uuid import uuid4

import pytest

from hydra.core.docstore import DocumentStore, KeyedModels, open_document_store
from hydra.core.eventlog import LogSpace
from hydra.core.events import EventType, HydraEvent
from hydra.discovery import ModelLifecycle
from hydra.edge.translation import GlossaryStore
from hydra.governance.config_registry import ConfigRegistry, FeatureFlags
from hydra.governance.recovery import backup
from hydra.governance.secrets import CredentialPolicy, SecretsBroker
from hydra.memory.failures import FailureMemory


@pytest.fixture(params=["file", "postgres"])
def docs(request):
    return DocumentStore(request.getfixturevalue("pg_url") if request.param == "postgres" else "")


def test_document_contract(docs, tmp_path):
    doc = docs.document("x.json", tmp_path / "x.json", refresh_s=0)
    assert doc.get() == {}
    assert doc.update(lambda d: {**d, "a": 1}) == {"a": 1}
    assert doc.set({"b": [1, 2]}) == {"b": [1, 2]}
    assert docs.document("x.json", tmp_path / "x.json").get() == {"b": [1, 2]}
    registry = KeyedModels(docs.document("y.json", tmp_path / "y.json"))
    registry.put("k", {"v": 1})
    assert registry.change("k", lambda cur: {**cur, "w": 2}) == {"v": 1, "w": 2}
    assert registry.all() == {"k": {"v": 1, "w": 2}}


def test_nodes_never_lose_each_others_updates(pg_url, tmp_path):
    nodes = [DocumentStore(pg_url).document("counter", tmp_path / "c.json", refresh_s=0) for _ in range(4)]

    def work(doc):
        for _ in range(25):
            doc.update(lambda d: {"n": d.get("n", 0) + 1})

    threads = [threading.Thread(target=work, args=(d,)) for d in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(d.get() == {"n": 100} for d in nodes)


def test_an_existing_file_is_adopted_once(pg_url, tmp_path):
    path = tmp_path / "flags.json"
    FeatureFlags(path).set("legacy", True)
    shared = FeatureFlags(path, docs=DocumentStore(pg_url))
    assert shared.enabled("legacy")
    shared.set("legacy", False)
    assert not FeatureFlags(path, docs=DocumentStore(pg_url)).enabled("legacy")  # not adopted again
    assert json.loads(path.read_text(encoding="utf-8"))["legacy"]["mode"] == "on"  # the file is kept


def test_engine_registries_are_shared(pg_url, tmp_path):
    a, b = DocumentStore(pg_url), DocumentStore(pg_url)
    flags_a, flags_b = FeatureFlags(tmp_path / "fa.json", docs=a), FeatureFlags(tmp_path / "fb.json", docs=b)
    for doc in (flags_a._registry.doc, flags_b._registry.doc):
        doc.refresh_s = 0
    flags_a.set("new_critic", "shadow")
    flags_b.set("belief_v3", "10%")  # b had not seen a's flag: both are kept
    assert set(flags_a.snapshot()) == {"new_critic", "belief_v3"} and flags_b.shadow("new_critic")

    gloss_a, gloss_b = GlossaryStore(tmp_path / "ga.json", docs=a), GlossaryStore(tmp_path / "gb.json", docs=b)
    gloss_a.put("legal", {"contract": "contrato"})
    gloss_b._registry.doc.refresh_s = 0
    assert gloss_b.put("legal", {"clause": "cláusula"}) == {"contract": "contrato", "clause": "cláusula"}

    life_a, life_b = ModelLifecycle(tmp_path / "la.json", docs=a), ModelLifecycle(tmp_path / "lb.json", docs=b)
    life_a.transition("m", "ACTIVE", "ok")
    life_b._registry.doc.refresh_s = 0
    life_b.transition("m", "DEPRECATED", "superseded")
    with pytest.raises(ValueError):
        life_a.transition("m", "CANDIDATE", "back")  # judged on the latest status, not on a's stale copy
    assert [h["to"] for h in ModelLifecycle(tmp_path / "lc.json", docs=a).state["m"]["history"]] == \
        ["ACTIVE", "DEPRECATED"]


def test_config_versions_are_unique_across_nodes(pg_url, tmp_path):
    nodes = [ConfigRegistry(tmp_path / f"c{k}", logs=LogSpace(pg_url, label="configs")) for k in range(4)]
    versions = []

    def work(reg, k):
        for i in range(5):
            versions.append(reg.commit("production", {f"k{k}": i}).version)

    threads = [threading.Thread(target=work, args=(r, k)) for k, r in enumerate(nodes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(versions) == list(range(1, 21))
    final = nodes[0].current("production")
    assert final.version == 20 and set(final.values) == {"k0", "k1", "k2", "k3"}
    rolled = nodes[1].rollback("production", 3, "ops")
    assert rolled.version == 21 and rolled.values == nodes[2].get("production", 3).values


def test_factory_registry_is_shared_by_gateway_and_workers(pg_url, tmp_path):
    from hydra.model_factory.adapters import AdapterRegistry, AdapterSpec
    from hydra.model_factory.manifest import FactoryJob
    from hydra.model_factory.store import FactoryStore

    api, worker = FactoryStore(tmp_path / "api", docs=DocumentStore(pg_url)), FactoryStore(
        tmp_path / "worker", docs=DocumentStore(pg_url))
    api.save_job(FactoryJob(kind="build", params={"target": "laptop"}))
    job = worker.save_job(FactoryJob(kind="evaluate", params={}))
    api._jobs.doc.refresh_s = 0
    assert {j.kind for j in api.jobs.values()} == {"build", "evaluate"} and job.id in api.jobs
    adapters = AdapterRegistry(tmp_path / "ad.json", docs=DocumentStore(pg_url))
    adapters.register(AdapterSpec(logical_model="hydra-legal", base_model="hydra-base", adapter_name="legal-v1",
                                  adapter_path="lora/legal"))
    assert AdapterRegistry(tmp_path / "other.json", docs=DocumentStore(pg_url)).for_base("hydra-base")


def _failure(model="m1"):
    return HydraEvent(task_id=uuid4(), type=EventType.MODEL_FAILED, source="test",
                      payload={"model": model, "kind": "timeout", "structured": True})


def _completed(model="m1"):
    return HydraEvent(task_id=uuid4(), type=EventType.MODEL_COMPLETED, source="test",
                      payload={"model": model, "structured": True})


async def test_failure_memory_adds_up_across_nodes(pg_url, tmp_path):
    a = FailureMemory(tmp_path / "fa.json", docs=DocumentStore(pg_url))
    b = FailureMemory(tmp_path / "fb.json", docs=DocumentStore(pg_url))
    for memory in (a, b):
        memory._doc.refresh_s = 0
        for _ in range(3):
            await memory.observe(_completed())
        await memory.observe(_failure())
    rate, runs = a.failure_rate("model", "m1", {"structured": True})
    assert (rate, runs) == (2 / 8, 8)  # 4 runs + 1 failure on each node
    assert a.report()[0]["failures"] == 2
    fresh = FailureMemory(tmp_path / "fc.json", docs=DocumentStore(pg_url))
    assert fresh.failure_rate("model", "m1") == (2 / 8, 8)


async def test_failure_memory_on_files_keeps_its_behaviour(tmp_path):
    memory = FailureMemory(tmp_path / "f.json", min_observations=3)
    await memory.observe(_completed())
    for _ in range(3):
        await memory.observe(_failure())
    assert memory.should_avoid("m1", {"structured": True})  # 3 failures in 4 runs
    assert FailureMemory(tmp_path / "f.json").failure_rate("model", "m1") == (0.75, 4)


def test_secret_vault_is_shared_and_never_stored_in_clear(pg_url, tmp_path):
    root = tmp_path / "secrets"
    legacy = SecretsBroker(root)
    legacy.put("secret://db/password", "s3cr3t", CredentialPolicy(ref="secret://db/password"))
    a = SecretsBroker(root, docs=DocumentStore(pg_url))
    b = SecretsBroker(root, docs=DocumentStore(pg_url))  # same broker key (keystore), another node
    assert a._load()["secret://db/password"] == "s3cr3t"  # secrets.enc adopted
    a.put("secret://api/token", "t0k3n")
    b._vault.refresh_s = 0
    assert b._load() == {"secret://db/password": "s3cr3t", "secret://api/token": "t0k3n"}
    assert "secret://db/password" in b.policies
    import psycopg

    with psycopg.connect(pg_url) as con:
        stored = json.dumps(con.execute("SELECT body FROM hydra_documents WHERE name = 'secrets/vault'").fetchone()[0])
    assert "s3cr3t" not in stored and "t0k3n" not in stored


def test_backup_exports_the_documents(pg_url, tmp_path):
    docs = DocumentStore(pg_url)
    FeatureFlags(tmp_path / "flags.json", docs=docs).set("x", True)
    data = tmp_path / "data"
    data.mkdir()
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[docs])
    assert "flags.json" in manifest.files


def test_document_backend_selection():
    assert open_document_store("file", "postgresql://x/y").backend == "file"
    assert open_document_store("auto", "").backend == "file"
    with pytest.raises(ValueError):
        open_document_store("postgres", "")


# ------------------------------------------------------------------------------------------ F3e-2
from types import SimpleNamespace  # noqa: E402

from hydra.planning.procedures import Procedure, ProcedureStore, ValueModel  # noqa: E402
from hydra.planning.simulator import CalibrationEngine, HistoricalSimulator  # noqa: E402
from hydra.replay import ImprovementLab  # noqa: E402
from hydra.runtime.observability import CognitiveTracer  # noqa: E402
from hydra.runtime.operating_metrics import collect_operating_metrics  # noqa: E402
from hydra.runtime.pg_stores import open_runtime_stores  # noqa: E402
from hydra.telemetry.metrics import InferenceRun  # noqa: E402


def test_planner_learning_adds_up_across_nodes(pg_url, tmp_path):
    nodes = [DocumentStore(pg_url) for _ in range(4)]
    hist = [HistoricalSimulator(tmp_path / f"h{k}.json", docs=d) for k, d in enumerate(nodes)]
    cal = [CalibrationEngine(tmp_path / f"c{k}.json", docs=d) for k, d in enumerate(nodes)]
    val = [ValueModel(tmp_path / f"v{k}.json", docs=d) for k, d in enumerate(nodes)]

    def work(k):
        for i in range(10):
            hist[k].record("code", "tests.run:all", success=i % 2 == 0, ms=10.0)
            cal[k].record("rules", "code", predicted=0.8, actual=True)
            val[k].update({"goal": "fix"}, "code.patch", reward=1.0)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = DocumentStore(pg_url)
    stats = HistoricalSimulator(tmp_path / "x.json", docs=fresh).stats["code|tests.run"]
    assert (stats.n, stats.successes, stats.total_ms) == (40, 20, 400.0)
    assert len(CalibrationEngine(tmp_path / "y.json", docs=fresh).data["rules|code"]) == 40
    assert ValueModel(tmp_path / "z.json", docs=fresh).score({"goal": "fix"}, ["code.patch"]) == {"code.patch": (1.0, 40)}


def test_procedures_keep_versions_and_statistics_across_nodes(pg_url, tmp_path):
    a = ProcedureStore(tmp_path / "pa.json", docs=DocumentStore(pg_url))
    b = ProcedureStore(tmp_path / "pb.json", docs=DocumentStore(pg_url))
    first = a.add(Procedure(name="p", domain="code", steps=["inspect", "patch"]))
    second = b.add(Procedure(name="p", domain="code", steps=["inspect", "patch", "test"]))
    assert second.version == 2 and second.parent == first.id  # b saw a's procedure under the lock
    for store in (a, b):
        store.record(first.id, success=True, cost=1.0, duration_ms=100.0)
    b._doc.refresh_s = 0
    assert b.items[first.id].executions == 2
    assert b.advance(first.id).status == "SHADOW"


def test_planner_stores_without_a_path_stay_in_memory():
    sim = HistoricalSimulator()
    sim.record("code", "verify", success=True, ms=1.0)
    assert sim.stats["code|verify"].n == 1 and HistoricalSimulator().stats == {}


async def test_improvement_ids_are_unique_across_nodes(pg_url, tmp_path):
    runs = [InferenceRun(task_id=uuid4(), task_type="code", model_id="m", role="critic", latency_ms=100.0,
                         success=False) for _ in range(30)]

    async def recent_runs():
        return runs

    def node(k):
        return SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path / f"n{k}"), documents=DocumentStore(pg_url),
                               telemetry=SimpleNamespace(recent_runs=recent_runs))

    first = await ImprovementLab(node(0)).analyze()
    second = await ImprovementLab(node(1)).analyze()  # sees node 0's proposals: no id is reused
    ids = [p.id for p in second]
    assert len(ids) == len(set(ids)) and {p.id for p in first} <= set(ids)


def test_operating_metrics_cover_the_whole_cluster(pg_url, tmp_path):
    nodes = [open_runtime_stores(tmp_path / f"n{k}.db", pg_url) for k in range(2)]
    for k, stores in enumerate(nodes):
        tracer = CognitiveTracer(store=stores.traces)
        for _ in range(3):
            with tracer.span("routing", trace_id=f"t{k}"):
                pass
        with pytest.raises(RuntimeError), tracer.span("inference", trace_id=f"t{k}"):
            raise RuntimeError("down")
    metrics = collect_operating_metrics(outbox=nodes[0].capture_uow.outbox, traces=nodes[1].traces)
    assert metrics.spans_total == 8 and metrics.spans_error == 2
    assert metrics.spans_by_name == {"inference": 2, "routing": 6}


# ------------------------------------------------------------------------------------------ F6a
from hydra.cli import main as hydra_main  # noqa: E402
from hydra.core.bootstrap import build_runtime  # noqa: E402
from hydra.core.config import Settings  # noqa: E402
from hydra.core.keystore import KeyStore  # noqa: E402


def _cluster_settings(tmp_path, url, **kw):
    return Settings(offline=True, sandbox_backend="subprocess", workspace_dir=tmp_path / "ws",
                    data_dir=tmp_path / "data", postgres_url=url, redis_url="", nats_url="", api_key="",
                    admin_token="", client_keys_file=tmp_path / "clients.json", require_shared_state=True,
                    runtime_api=False, **kw)


async def test_shared_state_is_required_when_asked(tmp_path):
    with pytest.raises(RuntimeError, match="local to this node: ledger"):
        await build_runtime(_cluster_settings(tmp_path, ""))


async def test_a_fully_shared_node_starts(pg_url, tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_KEYS_DIR", str(tmp_path / "keys"))
    settings = _cluster_settings(tmp_path, pg_url, key_backend="file", keys_dir=tmp_path / "keys")
    rt = await build_runtime(settings, keystore=KeyStore(tmp_path / "data", backend="file",
                                                         keys_dir=tmp_path / "keys"))
    try:
        assert rt.ledger.backend == "postgres" and rt.documents.backend == "postgres"
    finally:
        await rt.close()


def test_keys_export_writes_a_secret_ready_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "data"))
    assert hydra_main(["keys", "export", "--out", str(tmp_path / "out")]) == 0
    files = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert files == ["ledger-ed25519.key", "secrets-broker.key"]
    assert b"PRIVATE KEY" in (tmp_path / "out" / "ledger-ed25519.key").read_bytes()
    again = (tmp_path / "out" / "secrets-broker.key").read_bytes()
    hydra_main(["keys", "export", "--out", str(tmp_path / "out2")])
    assert (tmp_path / "out2" / "secrets-broker.key").read_bytes() == again  # the same keys, not new ones
