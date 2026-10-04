# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Provenance/IP ledger, licenses, BOM, releases, signing, supply chain, recovery."""

from __future__ import annotations

import json
import os
import pickle

import pytest

from hydra.artifacts.store import ArtifactStore
from hydra.core.hashing import merkle_proof, merkle_root, verify_merkle_proof
from hydra.governance.recovery import backup, restore
from hydra.ledger.bom import cyclonedx, write_bom_bundle
from hydra.ledger.chain import Ledger
from hydra.ledger.ip import (InventionStatus, IPRegistry, PriorArtReference, PriorArtSearch, TechnicalEffect,
                             TradeSecretVault, export_bundle, ip_experiment)
from hydra.ledger.licenses import LicenseEngine, LicenseRecord
from hydra.ledger.release import ReleaseArtifact, ReleaseBuilder, ReleaseGate, promote, verify_release
from hydra.ledger.signing import Signer
from hydra.training.signing import scan_model, sign_directory, verify_artifact


@pytest.fixture
def signer(tmp_path):
    return Signer.load_or_create(tmp_path / "keys")


def test_ledger_chain_signatures_anchors_and_tamper(tmp_path, signer):
    lg = Ledger(tmp_path / "l", signer, anchor_every=4)
    for i in range(9):
        lg.append("TASK_EXECUTED", {"i": i}, object_type="task", object_id=str(i))
    rep = lg.verify()
    assert rep.ok and rep.signatures_checked == 9 and len(lg.anchors()) == 2
    proof = lg.proof(3)
    assert verify_merkle_proof(proof["leaf"], [tuple(x) for x in proof["proof"]], proof["root"])
    lines = (tmp_path / "l" / "events.jsonl").read_text().splitlines()
    ev = json.loads(lines[4])
    ev["payload"]["i"] = 999
    lines[4] = json.dumps(ev)
    (tmp_path / "l" / "events.jsonl").write_text("\n".join(lines) + "\n")
    bad = Ledger(tmp_path / "l", signer).verify()
    assert not bad.ok and bad.broken_at == 5


def test_merkle_helpers():
    leaves = [f"{i:064x}" for i in range(5)]
    root = merkle_root(leaves)
    assert all(verify_merkle_proof(leaves[i], merkle_proof(leaves, i), root) for i in range(5))


def test_ip_lifecycle_disclosure_firewall_and_bundle(tmp_path, signer):
    lg = Ledger(tmp_path / "l", signer)
    reg = IPRegistry(tmp_path / "ip", lg)
    inv = reg.propose("KV-aware cognitive scheduling", features=["routing", "hardware state", "KV locality"])
    reg.add_effect(TechnicalEffect(invention_id=inv.invention_id, metric="TTFT", baseline_value=821,
                                   experimental_value=534, unit="ms"))
    assert reg.get(inv.invention_id).measurable_effects[0].improvement_pct == pytest.approx(34.96, abs=0.01)
    reg.add_prior_art(PriorArtSearch(invention_id=inv.invention_id,
                                     references=[PriorArtReference(identifier="REF-A", overlapping_features=["routing"])]))
    assert reg.feature_matrix(inv.invention_id)["features_not_found_in_refs"] == ["hardware state", "KV locality"]
    with ip_experiment(lg, "ablation", invention=inv.invention_id, capsule_dir=tmp_path / "caps") as exp:
        exp.results["ttft"] = 534
    assert (tmp_path / "caps" / exp.experiment_id / "hashes.txt").exists()
    reg.set_status(inv.invention_id, InventionStatus.PATENT_REVIEW, "counsel")
    gate = ReleaseGate(reg, LicenseEngine(), lg)
    dec = gate.evaluate(ReleaseArtifact(id="m", kind="model", invention_refs=[inv.invention_id],
                                        quality={"eval_passed": True, "score": 0.9}), "public")
    assert not dec.approved and any(r.startswith("ip:") for r in dec.blocked_reasons)
    bundle = export_bundle(reg, inv.invention_id, tmp_path / "b", signer)
    assert (bundle / "signature.sig").exists() and (bundle / "01_invention_description.md").exists()
    assert lg.verify().ok


def test_trade_secret_vault_acl(tmp_path, signer):
    lg = Ledger(tmp_path / "l", signer)
    v = TradeSecretVault(tmp_path / "v", lg)
    v.put("weights", "w=0.17", ["alice"], "luis")
    assert v.get("weights", "alice") == "w=0.17"
    with pytest.raises(PermissionError):
        v.get("weights", "mallory")
    assert b"0.17" not in (tmp_path / "v" / "weights.enc").read_bytes()
    assert sum(1 for e in lg.events() if e.event_type == "TRADE_SECRET_ACCESSED") == 3


def test_license_engine_profiles():
    eng = LicenseEngine()
    comps = [LicenseRecord(artifact_id="base", artifact_type="model", license_id="apache-2.0"),
             LicenseRecord(artifact_id="data", artifact_type="dataset", license_id="cc-by-nc-4.0")]
    assert eng.evaluate("enterprise-commercial", comps).status == "DENY"
    assert eng.evaluate("internal", comps).status == "ALLOW"
    assert eng.evaluate("enterprise-commercial", comps[:1]).status == "ALLOW"
    eng.grant_exception("data", "enterprise-commercial", "legal")
    assert eng.evaluate("enterprise-commercial", comps).status == "ALLOW"


def test_release_build_verify_promote(tmp_path, signer):
    p = ReleaseBuilder(tmp_path / "rel", signer).build("hydra-1.0.0", components={"router": "v1"})
    assert verify_release(p)["ok"]
    promote(p, "LAB", {"unit": True}, signer)
    assert verify_release(p)["ok"]  # promotions never touch the signed manifest
    with pytest.raises(ValueError):
        promote(p, "PRODUCTION", {"unit": True}, signer)
    (p / "sbom.json").write_text("tampered")
    assert not verify_release(p)["ok"]


def test_bom_cyclonedx(tmp_path):
    doc = cyclonedx()
    assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.6"
    hashes = write_bom_bundle(tmp_path / "bom", include_packages=False)
    assert "cyclonedx-mlbom.json" in hashes


def test_model_signing_and_supply_chain(tmp_path, signer):
    d = tmp_path / "adapter"
    d.mkdir()
    (d / "weights.bin").write_bytes(b"\x00" * 10)
    sign_directory(d, signer)
    assert verify_artifact(d, {signer.public_pem})["ok"]
    (d / "weights.bin").write_bytes(b"\x01" * 10)
    assert not verify_artifact(d)["ok"]

    class Evil:
        def __reduce__(self):
            return (os.system, ("echo pwned",))
    m = tmp_path / "model"
    m.mkdir()
    (m / "pytorch_model.bin").write_bytes(pickle.dumps(Evil()))
    (m / "config.json").write_text(json.dumps({"architectures": ["LlamaForCausalLM"]}))
    rep = scan_model(m)
    assert not rep.ok and any("dangerous global" in f for f in rep.findings)


def test_artifact_store_and_recovery(tmp_path, signer):
    data = tmp_path / "data"
    store = ArtifactStore(data / "artifacts")
    a = store.put("hello", task_id="t1")
    b = store.put("hello", task_id="t2")
    assert a.sha256 == b.sha256 and store.stats()["objects"] == 1
    Ledger(data / "ledger", signer).append("TASK_EXECUTED", {"x": 1})
    (data / "keys").mkdir(parents=True, exist_ok=True)
    (data / "keys" / "hydra-ed25519.pub.pem").write_text(signer.public_pem)
    man = backup(data, tmp_path / "b.tar.gz")
    assert man.ledger_events == 1
    rep = restore(tmp_path / "b.tar.gz", tmp_path / "restored")
    assert rep.ok and rep.ledger["ok"] and rep.artifacts["ok"]
