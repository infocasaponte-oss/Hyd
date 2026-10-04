# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The World Model on its event log: JSONL files on one node, PostgreSQL ``hydra_logs`` shared by all.

PostgreSQL cases run when HYDRA_IT_POSTGRES points at a disposable server whose user may create
databases (``pg_url`` in conftest gives each test its own database)."""
from __future__ import annotations

import json
import tarfile

import pytest

from hydra.core.eventlog import LogSpace
from hydra.governance.recovery import backup, restore
from hydra.world.model import BeliefStatus, EvidenceType, Observation, WorldModel


def obs(value, fam, et=EvidenceType.DOCUMENT, conf=0.72, subject="service-api"):
    return Observation(observer=fam, statement=f"{subject} port {value}", subject=subject, predicate="port",
                       value=value, confidence=conf, source_family=fam, evidence_type=et)


@pytest.fixture(params=["file", "postgres"])
def space(request):
    if request.param == "file":
        yield LogSpace(label="world")
        return
    s = LogSpace(request.getfixturevalue("pg_url"), label="world")
    yield s
    s.close()


def port_relations(w: WorldModel) -> dict[str, str | None]:
    return {r.object_id: r.valid_until for r in w.relations.values() if r.predicate == "port"}


def test_world_contract_on_both_backends(space, tmp_path):
    w = WorldModel(tmp_path / "world", logs=space)
    w.apply(w.observe(obs("8080", "tool:a", EvidenceType.TOOL_RESULT, 0.95)))
    w.apply(w.observe(obs("8081", "tool:b", EvidenceType.TOOL_RESULT, 0.95)))
    w.apply(w.observe(obs("8081", "human", EvidenceType.HUMAN_CONFIRMATION, 0.97)))
    w.snapshot()
    again = WorldModel(tmp_path / "world", logs=space)
    assert again.version == w.version == 3
    assert again.export() == w.export()
    # a closed relation keeps the instant it was closed, not the instant it was replayed
    closed = {k: v for k, v in port_relations(again).items() if v is not None}
    assert closed and closed == {k: v for k, v in port_relations(w).items() if v is not None}
    assert w.at_version(1).version == 1 and len(again.snapshots()) == 1
    assert [d["source"] for d in again.history(1)] == ["tool:b", "human"]


def test_delta_records_when_relations_were_closed(tmp_path):
    w = WorldModel(tmp_path / "world")
    w.apply(w.observe(obs("8080", "tool:a", EvidenceType.TOOL_RESULT, 0.95)))
    w.apply(w.observe(obs("8081", "tool:b", EvidenceType.TOOL_RESULT, 0.95)))
    w.apply(w.observe(obs("8081", "human", EvidenceType.HUMAN_CONFIRMATION, 0.97)))
    lines = [json.loads(x) for x in (tmp_path / "world" / "deltas.jsonl").read_text(encoding="utf-8").splitlines()]
    closing = [d for d in lines if d["relations_closed"]]
    assert closing and all(d["closed_at"] for d in closing)
    assert all(d["closed_at"] is None for d in lines if not d["relations_closed"])


def test_scratch_world_never_touches_the_real_one(tmp_path):
    w = WorldModel(tmp_path / "world")
    w.apply(w.observe(obs("8080", "tool:a", EvidenceType.TOOL_RESULT, 0.95)))
    before = w.export()
    s = w.scratch()
    s._apply(s.observe(obs("9090", "tool:b", EvidenceType.TOOL_RESULT, 0.95)))
    s._apply(s.observe(obs("9090", "human", EvidenceType.HUMAN_CONFIRMATION, 0.97)))
    assert any(v is not None for v in port_relations(s).values())
    assert w.export() == before and w.version == 1
    assert WorldModel(tmp_path / "world").version == 1


def test_two_nodes_share_one_world(pg_url, tmp_path):
    a = WorldModel(tmp_path / "a", logs=LogSpace(pg_url, label="world"), refresh_s=0)
    b = WorldModel(tmp_path / "b", logs=LogSpace(pg_url, label="world"), refresh_s=0)
    a.apply(a.observe(obs("8080", "doc-a")))
    b.apply(b.observe(obs("8081", "doc-b", conf=0.75)))
    assert a.version == b.version == 2
    assert {x.status for x in a.beliefs_about("service-api", "port")} == {BeliefStatus.CONTESTED}
    assert a.export() == b.export()


def test_reads_are_refreshed_at_most_every_refresh_s(pg_url, tmp_path):
    a = WorldModel(tmp_path / "a", logs=LogSpace(pg_url, label="world"), refresh_s=0)
    b = WorldModel(tmp_path / "b", logs=LogSpace(pg_url, label="world"), refresh_s=3600)
    a.apply(a.observe(obs("8080", "doc-a")))
    assert b.version == 0  # within the refresh window
    assert b.apply(b.observe(obs("8081", "doc-b"))) == 2  # applying replays everything before it


def test_existing_delta_file_is_adopted(pg_url, tmp_path):
    w = WorldModel(tmp_path / "world")
    w.apply(w.observe(obs("8080", "doc-a")))
    shared = WorldModel(tmp_path / "world", logs=LogSpace(pg_url, label="world"))
    assert shared.version == 1 and shared.export() == w.export()


def test_backup_exports_the_postgres_world_and_restore_rebuilds_it(pg_url, tmp_path):
    space = LogSpace(pg_url, label="world")
    data = tmp_path / "data"
    w = WorldModel(data / "world", logs=space)
    w.apply(w.observe(obs("8080", "doc-a")))
    w.apply(w.observe(obs("8081", "doc-b")))
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[space])
    assert "world/deltas.jsonl" in manifest.files
    with tarfile.open(tmp_path / "b.tar.gz") as tar:
        assert "data/world/deltas.jsonl" in tar.getnames()
    report = restore(tmp_path / "b.tar.gz", tmp_path / "restored")
    assert report.ok and report.world_version == 2
    space.close()
