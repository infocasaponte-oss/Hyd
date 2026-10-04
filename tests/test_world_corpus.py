# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""World Model + Belief Graph, Corpus Engine, Dataset Factory, Synthetic Foundry."""

from __future__ import annotations

import json

from hydra.core.contracts import HydraRequest, Message
from hydra.corpus.dedup import ContaminationGuard, Deduplicator, structural_hash
from hydra.corpus.factory import DatasetFactory, DatasetSpec, SyntheticPolicy, compile_record
from hydra.corpus.gates import CorpusCurator
from hydra.corpus.records import CorpusRecord, RecordType, RightsMetadata, TrainingStatus
from hydra.corpus.store import CorpusStore
from hydra.corpus.synthetic import SyntheticFoundry, SyntheticRecipe
from hydra.evals.suites import builtin_suites
from hydra.world.knowledge import GraphRAG, code_graph_delta
from hydra.world.model import BeliefStatus, EvidenceType, Observation, WorldModel


def obs(value, fam, et=EvidenceType.DOCUMENT, conf=0.72, subject="service-api"):
    return Observation(observer=fam, statement=f"{subject} port {value}", subject=subject, predicate="port",
                       value=value, confidence=conf, source_family=fam, evidence_type=et)


def test_contradiction_then_verification(tmp_path):
    w = WorldModel(tmp_path / "world")
    w.apply(w.observe(obs("8080", "doc-a")))
    w.apply(w.observe(obs("8081", "doc-b", conf=0.75)))
    assert {b.status for b in w.beliefs_about("service-api", "port")} == {BeliefStatus.CONTESTED}
    assert len(w.conflicts()) == 1
    w.apply(w.observe(obs("8081", "tool:docker", EvidenceType.TOOL_RESULT, 0.95)))
    by = {b.object_value: b for b in w.beliefs_about("service-api", "port", include_obsolete=True)}
    assert by["8081"].status == BeliefStatus.VERIFIED and by["8081"].confidence > 0.95
    assert by["8080"].status == BeliefStatus.OBSOLETE
    # time machine + persistence
    assert WorldModel(tmp_path / "world").version == w.version == 3
    assert len(w.at_version(2).conflicts()) == 1


def test_source_correlation_counts_one_family_once():
    w = WorldModel(None)
    for _ in range(3):  # three derivative models of the same base family
        w.apply(w.observe(obs("9000", "qwen-family", EvidenceType.MODEL, 0.5, subject="svc-z")))
    b = w.beliefs_about("svc-z", "port")[0]
    assert b.confidence <= 0.5 and b.status == BeliefStatus.HYPOTHESIS


def test_graph_rag_and_code_graph(tmp_path):
    w = WorldModel(None)
    w.apply(w.observe(obs("8081", "tool:docker", EvidenceType.TOOL_RESULT, 0.95)))
    pkt = GraphRAG(w).packet("¿qué puerto usa service-api?")
    assert any("8081" in f for f in pkt.verified_facts)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n\ndef twice(x):\n    return add(x, x)\n")
    (tmp_path / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    d = code_graph_delta(tmp_path, w, "demo")
    preds = {(r.subject_id.split(":")[-1], r.predicate, r.object_id.split(":")[-1]) for r in d.relations_added}
    assert ("twice", "CALLS", "add") in preds and ("test_add", "COVERS", "add") in preds


def test_corpus_gates_dedup_and_tombstone(tmp_path):
    store = CorpusStore(tmp_path / "corpus", CorpusCurator(dedup=Deduplicator(),
                                                           contamination=ContaminationGuard.from_suites(builtin_suites())))
    good = CorpusRecord(record_type=RecordType.SFT, input={"prompt": "Capital de Galicia"},
                        output={"answer": "Santiago de Compostela"}, quality=0.95, verification=0.95,
                        rights=RightsMetadata(training_allowed=True))
    assert store.ingest(good)[0].training_status == TrainingStatus.GOLD
    dup = good.model_copy(update={"id": "dup"})
    assert store.ingest(dup)[0].training_status == TrainingStatus.DUPLICATE
    secret = CorpusRecord(record_type=RecordType.SFT, input={"prompt": "token ghp_abcdefghijklmnopqrstuvwxyz0123456789"},
                          output={"answer": "ok"}, quality=0.99, verification=0.99,
                          rights=RightsMetadata(training_allowed=True))
    assert store.ingest(secret)[0].training_status == TrainingStatus.BLOCKED
    pii = CorpusRecord(record_type=RecordType.SFT, input={"prompt": "El cliente Juan Pérez escribe desde juan@x.com"},
                       output={"answer": "responder a juan@x.com"}, quality=0.9, verification=0.95,
                       rights=RightsMetadata(training_allowed=True))
    rec = store.ingest(pii)[0]
    assert "juan@x.com" not in json.dumps(rec.model_dump()) and rec.privacy.action == "PSEUDONYMIZE"
    not_allowed = CorpusRecord(record_type=RecordType.SFT, input={"prompt": "algo distinto"}, output={"answer": "x"},
                               quality=0.95, verification=0.95, rights=RightsMetadata(training_allowed=False))
    assert store.ingest(not_allowed)[0].training_status == TrainingStatus.QUARANTINED
    contaminated = CorpusRecord(record_type=RecordType.SFT, input={"prompt": builtin_suites()["coding"][0].prompt},
                                output={"answer": "x"}, quality=0.95, verification=0.95,
                                rights=RightsMetadata(training_allowed=True))
    assert store.ingest(contaminated)[0].training_status == TrainingStatus.BLOCKED
    store.add_lineage(good.id, "dataset:d1", "dataset_release")
    store.add_lineage("dataset:d1", "model:router-v1", "model")
    t = store.tombstone(good.id, "owner request")
    assert t.affected_datasets == ["dataset:d1"] and t.affected_models == ["model:router-v1"]
    assert CorpusStore(tmp_path / "corpus").get(good.id).training_status == TrainingStatus.TOMBSTONED


def test_structural_dedup():
    assert structural_hash("def f(a, b):\n    return a + b\n") == structural_hash("def g(x, y):\n    return x + y\n")
    assert structural_hash("def f(a, b):\n    return a + b\n") != structural_hash("def f(a, b):\n    return a - b\n")


async def test_dataset_factory_synthetic_cap_and_release(tmp_path):
    store = CorpusStore(tmp_path / "corpus")
    for i in range(6):
        store.ingest(CorpusRecord(record_type=RecordType.SFT, input={"prompt": f"pregunta real número {i} sobre HYDRA"},
                                  output={"answer": f"respuesta {i}", "messages": [
                                      {"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]},
                                  quality=0.95, verification=0.95, language="es",
                                  rights=RightsMetadata(training_allowed=True)))
    anchors = list(store.records.values())
    syn = await SyntheticFoundry().run(SyntheticRecipe(name="s", capability="reasoning.arithmetic", count=10), anchors)
    assert syn and all(r.synthetic and r.synthetic_generation == 1 for r in syn)
    for r in syn:
        store.ingest(r)
    rel = DatasetFactory(store).build(DatasetSpec(name="demo", format="sft", synthetic=SyntheticPolicy(max_fraction=0.25)))
    assert rel.synthetic_fraction <= 0.25 + 1e-9 and rel.rejected.get("synthetic_fraction_cap", 0) > 0
    assert DatasetFactory(store).verify_release(rel.id)["ok"]
    assert compile_record(anchors[0], "sft")["messages"][1]["content"] == "a0"


async def test_kernel_capture_builds_world_corpus_ledger(runtime):
    r = await runtime.kernel.run(HydraRequest(messages=[Message(role="user", content="¿Cuánto es 21 * 2?")]))
    learn = r.learning
    assert learn["world_version"] >= 1 and learn["corpus"]["candidates"] >= 2
    assert learn["ledger_event"]["sequence"] >= 1 and learn["artifacts"][0].startswith("cas://sha256/")
    assert runtime.ledger.verify().ok
    manifest = json.loads((runtime.settings.data_dir / "flight" / f"{r.meta.task_id}.json").read_text())
    assert manifest["answer_hash"] and manifest["events"]
    # the task, its model and a supported claim are in the world graph
    assert f"task/{r.meta.task_id}" in runtime.world.entities
