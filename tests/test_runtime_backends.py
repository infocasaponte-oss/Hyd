# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F3: the runtime line's hash chains (events, provenance) on the event log, files or PostgreSQL.

PostgreSQL cases need HYDRA_IT_POSTGRES (``pg_url`` in conftest gives each test its own database)."""
from __future__ import annotations

import threading
from uuid import uuid4

import pytest

from hydra.core.eventlog import FileLog, LogSpace
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord


def _event(store, aggregate, i, source=None):
    return store.append(event_type="hydra.test", aggregate_id=aggregate, producer="test", trace_id=f"t{i}",
                        payload={"i": i}, source_message_id=source)


def _record(i, source=None):
    return ProvenanceRecord(task_id=uuid4(), trace_id=f"t{i}", action="test", inputs={"i": i},
                            source_message_id=source)


@pytest.fixture(params=["file", "postgres"])
def logs(request, tmp_path):
    if request.param == "file":
        yield None
        return
    space = LogSpace(request.getfixturevalue("pg_url"), label="runtime")
    yield space
    space.close()


def _stores(logs, tmp_path):
    if logs is None:
        return JsonlEventStore(tmp_path / "events.jsonl"), ProvenanceLedger(tmp_path / "provenance.jsonl")
    return (JsonlEventStore(tmp_path / "events.jsonl", log=logs.open(tmp_path / "events.jsonl", JsonlEventStore.STREAM)),
            ProvenanceLedger(tmp_path / "provenance.jsonl",
                             log=logs.open(tmp_path / "provenance.jsonl", ProvenanceLedger.STREAM)))


def test_chain_contract_on_both_backends(logs, tmp_path):
    events, provenance = _stores(logs, tmp_path)
    aggregate, source = uuid4(), uuid4()
    first = _event(events, aggregate, 1, source)
    assert _event(events, aggregate, 2, source) == first  # idempotent by source message
    second = _event(events, aggregate, 3)
    assert (first.sequence, second.sequence, second.previous_hash) == (1, 2, first.event_hash)
    assert events.head == second.event_hash and events.verify_integrity().valid
    assert [e.sequence for e in events.for_aggregate(aggregate)] == [1, 2]
    r1 = provenance.append(_record(1, source))
    assert provenance.append(_record(2, source)).record_hash == r1.record_hash
    r2 = provenance.append(_record(3))
    assert r2.previous_hash == r1.record_hash and provenance.head == r2.record_hash
    assert provenance.verify_integrity().valid and provenance.verify_integrity().records == 2


def test_several_instances_on_one_file_keep_one_chain(tmp_path):
    a, b = JsonlEventStore(tmp_path / "e.jsonl"), JsonlEventStore(tmp_path / "e.jsonl")
    aggregate = uuid4()
    _event(a, aggregate, 1)
    _event(b, aggregate, 2)  # b sees a's event before chaining
    _event(a, aggregate, 3)
    report = JsonlEventStore(tmp_path / "e.jsonl").verify_integrity()
    assert report.valid and report.records == 3
    assert len(FileLog(tmp_path / "e.jsonl")) == 3


def test_nodes_build_one_valid_chain_without_duplicates(pg_url, tmp_path):
    nodes = [_stores(LogSpace(pg_url, label="runtime"), tmp_path / f"n{k}") for k in range(4)]
    shared_source = uuid4()
    aggregate = uuid4()

    def work(k):
        events, provenance = nodes[k]
        for i in range(10):
            _event(events, aggregate, i)
            provenance.append(_record(i))
        _event(events, aggregate, 99, shared_source)  # the same outbox message replayed by every node
        provenance.append(_record(99, shared_source))

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events, provenance = nodes[0]
    report = events.verify_integrity()
    assert report.valid and report.records == 41
    assert [e.sequence for e in events.for_aggregate(aggregate)] == list(range(1, 42))
    assert provenance.verify_integrity().valid and provenance.verify_integrity().records == 41
    assert {n[0].head for n in nodes} == {events.head}


def test_existing_chain_files_are_imported_and_continue(pg_url, tmp_path):
    local_events, local_provenance = _stores(None, tmp_path)
    aggregate = uuid4()
    last = _event(local_events, aggregate, 1)
    local_provenance.append(_record(1))
    space = LogSpace(pg_url, label="runtime")
    events, provenance = _stores(space, tmp_path)
    assert events.head == last.event_hash
    nxt = _event(events, aggregate, 2)
    assert nxt.sequence == 2 and nxt.previous_hash == last.event_hash and events.verify_integrity().valid
    assert provenance.verify_integrity().records == 1
    space.close()


def test_runtime_backend_follows_the_settings(monkeypatch):
    from hydra.core.config import Settings
    from hydra.runtime.config import Settings as RuntimeSettings

    monkeypatch.setenv("HYDRA_RUNTIME_BACKEND", "postgres")
    monkeypatch.setenv("HYDRA_POSTGRES_URL", "postgresql://x/y")
    view = RuntimeSettings.from_platform(Settings(_env_file=None))
    assert (view.runtime_backend, view.postgres_url) == ("postgres", "postgresql://x/y")


def test_file_log_rereads_a_rewritten_file(tmp_path):
    path = tmp_path / "x.jsonl"
    log = FileLog(path)
    for i in range(3):
        log.append(f'{{"i": {i}}}')
    assert [s for s, _ in log.read(2)] == [3]  # resumes from the cached tail
    path.write_text('{"i":   "rewritten history, longer than before"}\n', encoding="utf-8")
    assert len(log) == 1 and [line for _, line in log.read()] == ['{"i":   "rewritten history, longer than before"}']
    assert log.append('{"i": 9}')[0] == 2


# ------------------------------------------------------------------------------------------ F3b
import json  # noqa: E402

from hydra.runtime.deployment import Deployment, DeploymentState  # noqa: E402
from hydra.runtime.deployment_controller import (  # noqa: E402
    CANARY_EVIDENCE_SEQ,
    SHADOW_EVIDENCE_SEQ,
    DeploymentController,
)
from hydra.runtime.deployment_registry import DeploymentRegistry  # noqa: E402
from hydra.runtime.deployment_store import DeploymentStore  # noqa: E402
from hydra.runtime.model_factory import BuildState, ModelLineage, ModelVariant  # noqa: E402
from hydra.runtime.runtime_evidence import RuntimeEvidenceStore  # noqa: E402


def _deployment(generation=1, state=DeploymentState.CANDIDATE):
    variant = ModelVariant(lineage=ModelLineage(base_model="base", base_model_sha256="a" * 64), quantization="Q4_K_M",
                           artifact_path="model.gguf", artifact_sha256="b" * 64, state=BuildState.PROMOTED)
    return Deployment(variant=variant, capabilities={"reasoning.general"}, state=state, generation=generation)


def _canary(store, vid, n, latency=10.0):
    for i in range(n):
        store.append(trace_id=f"c{i}", capability="reasoning.general", primary_variant_id="active",
                     primary_output="a", canary_variant_id=vid, canary_error=False, canary_latency_ms=latency)


def test_evidence_from_every_node_counts(pg_url, tmp_path):
    a, b = (RuntimeEvidenceStore(tmp_path / f"{k}.jsonl", log=LogSpace(pg_url, label="runtime").open(
        tmp_path / f"{k}.jsonl", RuntimeEvidenceStore.STREAM)) for k in "ab")
    _canary(a, "v", 3)
    start = b.position()
    _canary(a, "v", 2)
    _canary(b, "v", 5)
    assert start == 3 and a.canary_evidence("v").requests == 10
    assert b.canary_evidence("v", start).requests == 7


def test_legacy_byte_offsets_become_sequence_numbers(tmp_path):
    path = tmp_path / "runtime-evidence.jsonl"
    store = RuntimeEvidenceStore(path)
    item = _deployment(state=DeploymentState.CANARY)
    _canary(store, str(item.variant_id), 4)
    offset = len(b"".join(path.read_bytes().splitlines(keepends=True)[:3]))  # phase began after 3 records
    _canary(store, str(item.variant_id), 2)
    registry = DeploymentRegistry()
    item.metadata["canary_evidence_offset"] = offset
    registry.add(item)
    controller = DeploymentController(registry, runtime_evidence=store)
    assert controller.migrate_phase_starts() == 1
    assert item.metadata[CANARY_EVIDENCE_SEQ] == 3 and "canary_evidence_offset" not in item.metadata
    assert controller.measure_canary(item).requests == 3  # records 4..6 only
    assert controller.migrate_phase_starts() == 0


def test_a_legacy_offset_without_its_file_restarts_the_phase(tmp_path):
    shared = RuntimeEvidenceStore(tmp_path / "gone.jsonl", log=FileLog(tmp_path / "elsewhere.jsonl"))
    _canary(shared, "v", 5)
    registry = DeploymentRegistry()
    item = _deployment(state=DeploymentState.SHADOW)
    item.metadata["shadow_evidence_offset"] = 1234
    registry.add(item)
    DeploymentController(registry, runtime_evidence=shared).migrate_phase_starts()
    assert item.metadata[SHADOW_EVIDENCE_SEQ] == 5 and "evidence_restarted_at" in item.metadata


def _shared_store(pg_url, tmp_path, name):
    space = LogSpace(pg_url, label="runtime")
    return DeploymentStore(tmp_path / f"{name}.json", log=space.open(tmp_path / f"{name}.jsonl", DeploymentStore.STREAM))


def test_nodes_share_one_deployment_registry(pg_url, tmp_path):
    store_a, store_b = _shared_store(pg_url, tmp_path, "a"), _shared_store(pg_url, tmp_path, "b")
    reg_a, reg_b = store_a.load(), store_b.load()
    one, two = _deployment(1), _deployment(2)
    store_a.mutate(reg_a, lambda r: r.add(one))
    store_b.mutate(reg_b, lambda r: r.add(two))  # b had not seen `one`: it is kept, not overwritten
    assert set(reg_b.deployments) == {str(one.variant_id), str(two.variant_id)}
    assert store_a.sync(reg_a) and set(reg_a.deployments) == set(reg_b.deployments)
    assert not store_a.sync(reg_a)  # nothing new
    with pytest.raises(ValueError):  # a failing operation leaves the stored state as it was
        store_a.mutate(reg_a, lambda r: r.deployments[str(one.variant_id)].transition(DeploymentState.ACTIVE))
    assert reg_a.deployments[str(one.variant_id)].state == DeploymentState.CANDIDATE
    store_a.mutate(reg_a, lambda r: r.deployments[str(one.variant_id)].transition(DeploymentState.SHADOW))
    assert store_b.sync(reg_b) and reg_b.deployments[str(one.variant_id)].state == DeploymentState.SHADOW


def test_concurrent_admin_operations_are_all_kept(pg_url, tmp_path):
    stores = [_shared_store(pg_url, tmp_path, f"n{k}") for k in range(4)]
    registries = [s.load() for s in stores]
    added = [[_deployment(10 * k + i) for i in range(5)] for k in range(4)]

    def work(k):
        for d in added[k]:
            stores[k].mutate(registries[k], lambda r, d=d: r.add(d))

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_shared_store(pg_url, tmp_path, "fresh").load().deployments) == 20


def test_existing_deployments_file_is_adopted(pg_url, tmp_path):
    registry = DeploymentRegistry()
    registry.add(_deployment(3, DeploymentState.ACTIVE))
    DeploymentStore(tmp_path / "d.json").save(registry)
    shared = DeploymentStore(tmp_path / "d.json", log=LogSpace(pg_url, label="runtime").open(
        tmp_path / "d.jsonl", DeploymentStore.STREAM))
    assert shared.load().active_for("reasoning.general").generation == 3
    assert json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))  # the file is kept


def test_single_node_mutate_restores_memory_on_failure(tmp_path):
    store = DeploymentStore(tmp_path / "d.json")
    registry = DeploymentRegistry()
    item = _deployment()
    store.mutate(registry, lambda r: r.add(item))
    with pytest.raises(ValueError):
        store.mutate(registry, lambda r: r.deployments[str(item.variant_id)].transition(DeploymentState.ACTIVE))
    assert registry.deployments[str(item.variant_id)].state == DeploymentState.CANDIDATE
    assert store.load().deployments[str(item.variant_id)].state == DeploymentState.CANDIDATE


# ------------------------------------------------------------------------------------------ F3d
from hydra.artifacts.blobs import LocalBlobs  # noqa: E402
from hydra.governance.recovery import backup  # noqa: E402
from hydra.runtime.artifacts import ArtifactStore as RuntimeArtifacts  # noqa: E402
from hydra.runtime.corpus import CorpusGate, CorpusRecord, CorpusStore as RuntimeCorpus  # noqa: E402
from hydra.runtime.replay import ReplayManifest, ReplayStore  # noqa: E402
from hydra.runtime.replay_executor import AuditReplayExecutor  # noqa: E402


def _space(pg_url):
    return LogSpace(pg_url, label="runtime")


def test_runtime_corpus_keeps_a_record_once_across_nodes(pg_url, tmp_path):
    nodes = [RuntimeCorpus(tmp_path / f"c{k}.jsonl", log=_space(pg_url).open(tmp_path / f"c{k}.jsonl",
                                                                              RuntimeCorpus.STREAM)) for k in range(4)]
    record = CorpusGate().evaluate(CorpusRecord(task_id=uuid4(), belief_id=uuid4(), artifact_hashes=["a" * 64]))
    results = []
    threads = [threading.Thread(target=lambda n=n: results.append(n.append_once(record))) for n in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, False, False, True]
    assert len(nodes[0].log) == 1 and nodes[3].contains_hash(record.content_hash)


def test_runtime_corpus_file_format_is_unchanged(tmp_path):
    store = RuntimeCorpus(tmp_path / "corpus.jsonl")
    record = CorpusGate().evaluate(CorpusRecord(task_id=uuid4(), belief_id=uuid4(), artifact_hashes=["b" * 64]))
    assert store.append_once(record) and not store.append_once(record)
    assert CorpusRecord.model_validate_json((tmp_path / "corpus.jsonl").read_text(encoding="utf-8")) == record


def test_replay_manifests_are_visible_from_every_node(pg_url, tmp_path):
    legacy = ReplayStore(tmp_path / "replay")
    old = legacy.put(ReplayManifest(task_id=uuid4(), trace_id="t0", hydra_version="1"))
    a = ReplayStore(tmp_path / "replay", log=_space(pg_url).open(tmp_path / "r.jsonl", ReplayStore.STREAM))
    b = ReplayStore(tmp_path / "replay", log=_space(pg_url).open(tmp_path / "r.jsonl", ReplayStore.STREAM))
    task = uuid4()
    a.put(ReplayManifest(task_id=task, trace_id="t1", hydra_version="1"))
    assert b.get(task).trace_id == "t1"
    assert b.get(old.task_id).manifest_hash == old.manifest_hash  # written before the shared log
    assert b.get(uuid4()) is None


def test_runtime_artifacts_are_shared_and_audited_on_another_node(pg_url, tmp_path):
    blobs = LocalBlobs(tmp_path / "shared-objects")  # a volume every node mounts (or an S3 bucket)
    root_a = tmp_path / "a"
    legacy = RuntimeArtifacts(root_a).put_text(task_id=uuid4(), kind="patch", text="written before")
    a = RuntimeArtifacts(root_a, blobs=blobs, log=_space(pg_url).open(tmp_path / "x.jsonl", RuntimeArtifacts.STREAM))
    b = RuntimeArtifacts(tmp_path / "b", blobs=blobs,
                         log=_space(pg_url).open(tmp_path / "y.jsonl", RuntimeArtifacts.STREAM))
    made = a.put_text(task_id=uuid4(), kind="patch", text="made on node a")
    assert b.get_text(made.sha256) == "made on node a"
    assert a.get_text(legacy.sha256) == "written before" and blobs.exists(legacy.sha256)  # copied on first read
    assert b.get_text(legacy.sha256) == "written before"
    events, provenance = _stores(None, tmp_path / "chains")
    manifest = ReplayStore(tmp_path / "replay").put(ReplayManifest(task_id=uuid4(), trace_id="t", hydra_version="1",
                                                                   artifact_hashes=[made.sha256]))
    executor = AuditReplayExecutor(events=events, provenance=provenance, artifacts=b)
    assert executor.audit(manifest).valid
    blobs.overwrite(made.sha256, b"tampered")
    assert executor.audit(manifest).error == f"artifact hash mismatch: {made.sha256}"


def test_backup_exports_the_runtime_streams(pg_url, tmp_path):
    space = _space(pg_url)
    events = JsonlEventStore(tmp_path / "events.jsonl", log=space.open(tmp_path / "events.jsonl", JsonlEventStore.STREAM))
    _event(events, uuid4(), 1)
    data = tmp_path / "data"
    data.mkdir()
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[space])
    assert "runtime/events.jsonl" in manifest.files
    space.close()
