# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The invention registry on its event log: JSONL files on one node, PostgreSQL ``hydra_logs`` shared by all.

PostgreSQL cases run when HYDRA_IT_POSTGRES points at a disposable server whose user may create
databases (``pg_url`` in conftest gives each test its own database)."""
from __future__ import annotations

import json
import threading

import pytest

from hydra.core.eventlog import LogSpace
from hydra.governance.recovery import backup, restore
from hydra.ledger.chain import Ledger
from hydra.ledger.ip import ContributionRecord, InventionRecord, InventionStatus, IPRegistry, TechnicalEffect
from hydra.ledger.signing import Signer


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger", Signer.generate())


@pytest.fixture(params=["file", "postgres"])
def space(request):
    if request.param == "file":
        yield LogSpace(label="ip")
        return
    s = LogSpace(request.getfixturevalue("pg_url"), label="ip")
    yield s
    s.close()


def test_registry_contract_on_both_backends(space, ledger, tmp_path):
    reg = IPRegistry(tmp_path / "ip", ledger, logs=space)
    a = reg.propose("KV-aware scheduling", features=["routing", "KV locality"])
    b = reg.propose("Belief decay", features=["decay"])
    assert (a.invention_id, b.invention_id) == ("INV-HYDRA-0001", "INV-HYDRA-0002")
    reg.add_effect(TechnicalEffect(invention_id=a.invention_id, metric="TTFT", baseline_value=800,
                                   experimental_value=600, unit="ms"))
    reg.set_status(a.invention_id, InventionStatus.PATENT_REVIEW, "counsel", "promising")
    reg.link(a.invention_id, commit="abc123", artifact="cas://sha256/00")
    returned = reg.add_contribution(ContributionRecord(invention_id=a.invention_id, contributor_id="luis",
                                                       contribution_type="idea"))
    assert returned.contributor_id == "luis"
    again = IPRegistry(tmp_path / "ip", ledger, logs=space)
    inv = again.get(a.invention_id)
    assert inv.status == InventionStatus.PATENT_REVIEW and inv.measurable_effects[0].improvement_pct == 25.0
    assert inv.related_commits == ["abc123"] and "luis" in inv.contributors
    assert again.portfolio()["total"] == 2
    events = [e.event_type for e in ledger.for_object("invention", a.invention_id)]
    assert events[:2] == ["INVENTION_CANDIDATE_CREATED", "TECHNICAL_EFFECT_OBSERVED"]
    assert "INVENTION_STATUS_CHANGED" in events and "CODE_COMMIT_REGISTERED" in events
    with pytest.raises(KeyError):
        reg.add_embodiment("INV-HYDRA-9999", "nothing")
    assert len(IPRegistry(tmp_path / "ip", ledger, logs=space).inventions) == 2


def test_legacy_snapshot_is_converted_once(ledger, tmp_path):
    root = tmp_path / "ip"
    root.mkdir()
    old = InventionRecord(invention_id="INV-HYDRA-0001", title="old")
    (root / "inventions.json").write_text(json.dumps({old.invention_id: old.model_dump(mode="json")}),
                                          encoding="utf-8")
    reg = IPRegistry(root, ledger)
    assert reg.get("INV-HYDRA-0001").title == "old"
    assert reg.propose("new").invention_id == "INV-HYDRA-0002"
    assert len(IPRegistry(root, ledger).inventions) == 2  # not converted again
    assert (root / "inventions.json").exists()


def test_two_nodes_never_mint_the_same_id_nor_lose_changes(pg_url, ledger, tmp_path):
    nodes = [IPRegistry(tmp_path / f"n{k}", ledger, logs=LogSpace(pg_url, label="ip"), refresh_s=3600)
             for k in range(4)]
    ids: list[str] = []

    def propose(k):
        for i in range(5):
            ids.append(nodes[k].propose(f"idea {k}.{i}").invention_id)

    threads = [threading.Thread(target=propose, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ids) == [f"INV-HYDRA-{n:04d}" for n in range(1, 21)]
    # concurrent changes to the same invention from stale nodes are all kept
    target = ids[0]
    workers = [threading.Thread(target=nodes[k].add_embodiment, args=(target, f"variant {k}")) for k in range(4)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    fresh = IPRegistry(tmp_path / "fresh", ledger, logs=LogSpace(pg_url, label="ip"))
    assert sorted(fresh.get(target).alternative_embodiments) == [f"variant {k}" for k in range(4)]


def test_backup_exports_the_postgres_registry(pg_url, ledger, tmp_path):
    space = LogSpace(pg_url, label="ip")
    data = tmp_path / "data"
    IPRegistry(data / "ip", ledger, logs=space).propose("exported")
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[space])
    assert "ip/inventions.jsonl" in manifest.files
    assert restore(tmp_path / "b.tar.gz", tmp_path / "restored").ok
    assert IPRegistry(tmp_path / "restored" / "ip", ledger).get("INV-HYDRA-0001").title == "exported"
    space.close()
