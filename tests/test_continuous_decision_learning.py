# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json
import random

import numpy as np
import pytest

from hydra.hyd.continual import ContinualRanker
from hydra.hyd.continual_controller import ContinualController
from hydra.router.decision_contract import CRITERIA
from hydra.training import decision_active_learning as al
from hydra.training.decision_candidates import PARTS, train_candidate, validate
from hydra.training.decision_challenges import generate
from hydra.training.decision_compare import paired_summary
from hydra.training.decision_rounds import RoundController


def write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.fixture
def partitions(tmp_path):
    paths = {}
    for part in PARTS:
        rows = []
        for i, label in enumerate(CRITERIA):
            text = f"Solicitud {label} de escenario {part} número {i}"
            rows.append({"id": f"{part}-{i}", "text": text, "expected": label,
                "group_id": f"scenario-{part}-{i}", "split": part,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "training_allowed": part == "fit"})
        paths[part] = write(tmp_path / (part + ".jsonl"), rows)
    return paths


@pytest.mark.parametrize("k", [0, -1, 501, True])
def test_selection_rejects_invalid_budget(k):
    with pytest.raises(ValueError):
        al.select(None, ["texto"], k, "random", random.Random(0))


def test_calibration_leak_is_rejected(partitions, tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        al.simulate([partitions["fit"]], [], partitions["fit"], partitions["test"], rounds=1, seeds=1)


def test_all_declared_partition_boundaries(partitions):
    rows = {k: al.read_rows(v) for k, v in partitions.items()}
    rows["dev"][0]["group_id"] = rows["fit"][0]["group_id"]
    with pytest.raises(ValueError, match="overlap"):
        validate(rows)


def test_queue_tamper_and_review_events(partitions, tmp_path):
    pool = write(tmp_path / "pool.jsonl", [{"text": "Implementa una cola de tareas nueva", "group_id": "new"}])
    queue = tmp_path / "queue"
    al.make_queue([partitions["fit"]], pool, queue, strategy="random", k=1)
    rows = al.read_rows(queue / "queue.jsonl")
    rows[0].update(text="Pregunta alterada deliberadamente", human_label="coding", reviewer="test")
    write(queue / "queue.jsonl", rows)
    with pytest.raises(ValueError, match="modified"):
        al.admit(queue, tmp_path / "bad.jsonl")
    original = al.read_rows(queue / "original.jsonl")[0]
    al.record_review(queue, original["id"], "coding", "test")
    al.record_review(queue, original["id"], "tool_use", "correction")
    # Events bind the original; a manipulated editable compatibility file is not admitted.
    admitted = tmp_path / "admitted.jsonl"
    al.admit(queue, admitted)
    result = al.read_rows(admitted)[0]
    assert result["text"] == original["text"] and result["expected"] == "tool_use"
    assert result["text_sha256"] == original["text_sha256"]
    assert result["review_event"]["reviewed_at"]


def test_budget_records_effective_acquisitions(partitions, tmp_path):
    rows = al.read_rows(partitions["dev"])
    for r in rows:
        r["training_allowed"] = True
    pool = write(tmp_path / "pool.jsonl", rows[:2])
    result = al.simulate([partitions["fit"]], [pool], partitions["cal_prob"], partitions["test"],
                         rounds=3, batch=10, seeds=1)
    assert result["labels_budget"] == 30
    assert all(s["effective_labels_per_run"] == [2] for s in result["strategies"].values())


def test_candidate_selection_and_runtime_binding(partitions, tmp_path):
    out = tmp_path / "candidate"
    report = train_candidate(partitions, out, {"kind": "hash", "dims": 64, "memory": True}, epochs=10)
    assert not report["authority"] and not report["independent_test"]
    assert len(report["selection_trials"]) == 3 and len(report["memory_trials"]) == 3
    loaded = ContinualRanker.load(out / "model.json")
    assert np.isclose(sum(loaded.predict_proba("Una pregunta").values()), 1)
    controller = ContinualController(out / "model.json", out / "calibration.json")
    assert not controller.authority.enabled
    data = json.loads((out / "model.json").read_text())
    data["implementation_sha256"] = "bad"
    (out / "model.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mismatch"):
        ContinualRanker.load(out / "model.json")


def test_round_waits_restarts_and_never_promotes(partitions, tmp_path):
    pool = write(tmp_path / "pool.jsonl", [{"text": "Programa una cola de tareas verdaderamente nueva", "group_id": "new-case"}])
    root = tmp_path / "learning"
    cfg = {"paths": {k: str(v) for k, v in partitions.items()}, "pool": str(pool),
           "batch": 1, "min_admitted": 1, "epochs": 5, "encoder": {"kind": "hash", "dims": 64}}
    c = RoundController(root)
    c.create("first", cfg)
    assert c.tick("first")["state"] == "WAITING_REVIEW"
    case = al.read_rows(root / "first/review/original.jsonl")[0]
    c.review("first", case["id"], "coding", "test-human")
    resumed = RoundController(root)
    assert resumed.tick("first", train=False)["state"] == "SNAPSHOT_READY"
    assert not list((root / "first").glob("candidate-*"))
    assert resumed.tick("first")["state"] == "WAITING_APPROVAL"
    before = list((root / "first").glob("candidate-*"))
    assert resumed.tick("first")["state"] == "WAITING_APPROVAL"
    assert list((root / "first").glob("candidate-*")) == before
    assert not resumed.status("first")["result"]["authority"]
    proposals = al.read_rows(root / "first/challenge-proposals/proposals.jsonl")
    assert all(r["expected"] is None and r["training_allowed"] is False for r in proposals)
    resumed.next_round("first", "second")
    assert resumed.tick("second")["state"] == "NO_NEW_DATA"
    export = tmp_path / "round.zip"
    resumed.export("first", export)
    import zipfile
    with zipfile.ZipFile(export) as archive:
        assert set(f"inputs/{p}.jsonl" for p in PARTS) <= set(archive.namelist())
        assert not json.loads(archive.read("portable-manifest.json"))["authority"]
    with resumed.lease("first"), pytest.raises(RuntimeError, match="busy"):
        resumed.tick("first")
    pool.write_text("modified")
    with pytest.raises(ValueError, match="changed"):
        resumed.tick("first")


def test_synthetic_proposals_do_not_become_gold(partitions, tmp_path):
    out = tmp_path / "challenge"
    generate(partitions["fit"], out, limit=10)
    rows = al.read_rows(out / "proposals.jsonl")
    assert len(rows) == 10 and all(r["expected"] is None and r["source_kind"] == "synthetic" for r in rows)
    with pytest.raises(ValueError, match="held-out"):
        generate(partitions["test"], tmp_path / "bad")


def test_paired_comparison_rejects_different_texts():
    row = {"id": "a", "text_sha256": "digest", "group_id": "a", "expected": "coding",
           "selected": "coding", "probabilities": {k: float(k == "coding") for k in CRITERIA}}
    assert paired_summary([row], [row])["family_mean_delta"] == 0
    with pytest.raises(ValueError, match="content"):
        paired_summary([row], [{**row, "text_sha256": "another"}])


def test_review_api_requires_admin_and_resumes(partitions, tmp_path):
    from fastapi import Depends, FastAPI, HTTPException, Header
    from fastapi.testclient import TestClient
    from hydra.api.decision_learning_routes import register
    def auth(x_hydra_admin_token: str = Header(default="")):
        if x_hydra_admin_token != "local-test-admin":
            raise HTTPException(403)
    root = tmp_path / "factory"
    pool = write(tmp_path / "pool.jsonl", [{"text": "<script>texto literal</script> programa algo nuevo", "group_id": "api-new"}])
    controller = RoundController(root)
    controller.create("api", {"paths": {k: str(v) for k, v in partitions.items()},
        "pool": str(pool), "batch": 1, "min_admitted": 1, "epochs": 2})
    controller.tick("api")
    app = FastAPI()
    register(app, [Depends(auth)], root)
    with TestClient(app) as client:
        path = "/hydra/v1/learning/rounds/api"
        assert client.get(path).status_code == 403
        headers = {"x-hydra-admin-token": "local-test-admin"}
        data = client.get(path, headers=headers).json()
        identity = data["cases"][0]["id"]
        assert client.post(path + "/review", headers=headers, json={"case_id": identity,
            "label": "coding", "reviewer": "human"}).status_code == 200
        assert identity in client.get(path, headers=headers).json()["reviews"]
        assert client.get("/hydra/v1/learning/review").headers["x-content-type-options"] == "nosniff"
