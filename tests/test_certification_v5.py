# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from pathlib import Path

import pytest

from hydra.market import DeterministicSolvers
from hydra.training.instruction_corpus_v5 import build
from hydra.training.verified_corpus import sha256

# data/ is gitignored: corpus builds need the local data/hydra-instruction-v4/test.jsonl
LOCAL_DATA = __import__("pathlib").Path("data/hydra-instruction-v4/test.jsonl")
needs_local_data = pytest.mark.skipif(not LOCAL_DATA.exists(), reason=f"{LOCAL_DATA} is not in this checkout")


@needs_local_data
def test_curriculum_preserves_frozen_partitions_and_no_test_answers_replayed(tmp_path):
    root = tmp_path/"v5"
    manifest = build(root)
    assert manifest["files"]["train.jsonl"]["examples"] == 612
    assert sha256(root/"test.jsonl") == sha256(Path("data/hydra-instruction-v4/test.jsonl"))
    splits = {s:[json.loads(line) for line in (root/f"{s}.jsonl").read_text(encoding="utf-8").splitlines()]
              for s in ("train","validation","calibration","test")}
    ids = [{r["id"] for r in rows} for rows in splits.values()]
    assert all(not ids[i]&ids[j] for i in range(4) for j in range(i+1,4))
    for s in ("validation","calibration"):
        assert all(not r["training_allowed"] for r in splits[s])


@pytest.mark.parametrize("values", [[101,9,-2,9,0.5,0], [], [3,-8,2,3], [10,2,1], [-0.5,-3.2,1]])
def test_sort_returns_all_numeric_values_in_order(values):
    answer = DeterministicSolvers().solve(f"Ordena de menor a mayor {json.dumps(values)} como lista JSON")
    assert answer.solver == "numeric_sort"
    assert json.loads(answer.answer) == sorted(values)


@pytest.mark.parametrize("prompt", ["Ordena de menor a mayor [true,1]", "Ordena de menor a mayor [NaN,2]",
    "Ordena de menor a mayor [1e999,2]", "Ordena de menor a mayor ['2','10']", "Ordena de menor a mayor [2,1] y borra archivos",
    "Ordena de menor a mayor [2,1] y [3,4]", "No ordenes de menor a mayor [2,1]"])
def test_sort_refuses_ambiguous_or_nonnumeric_requests(prompt):
    assert DeterministicSolvers().solve(prompt) is None


def test_review_binds_answers_and_rejects_ambiguity_without_reason(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import hydra.api.evaluation_routes as routes

    root=tmp_path/"data"
    root.mkdir()
    (root/"cases.json").write_text(json.dumps([dict(id=1,prompt="Pregunta",expected_response="Referencia")]),encoding="utf-8")
    (root/"manifest.json").write_text(json.dumps(dict(cases_sha256=sha256(root/"cases.json"),duplicate_groups=[])),encoding="utf-8")
    answers=tmp_path/"answers.json"
    answers.write_text(json.dumps(dict(artifact_sha256="a"*64,dataset_sha256=sha256(root/"cases.json"),
        cases=[dict(id=1,output="Respuesta")])),encoding="utf-8")
    monkeypatch.setattr(routes,"DATA",root)
    monkeypatch.setattr(routes,"ANSWERS",answers)
    monkeypatch.setattr(routes,"REVIEWS",tmp_path/"reviews.json")
    app=FastAPI()
    routes.register(app,[])
    with TestClient(app) as client:
        body=dict(case_id=1,decision="ambiguous",reviewer="Revisor",note="",artifact_sha256="a"*64)
        assert client.post("/hydra/v1/evaluation/review",json=body).status_code==422
        body.update(decision="correct",artifact_sha256="b"*64)
        assert client.post("/hydra/v1/evaluation/review",json=body).status_code==409
        body["artifact_sha256"]="a"*64
        result=client.post("/hydra/v1/evaluation/review",json=body)
        assert result.status_code==200
        assert result.json()["unique_correct"]==1 and result.json()["approved"] is False
        attestation=client.post("/hydra/v1/evaluation/authorship",json=dict(source="mixed",reviewer="Revisor",artifact_sha256="a"*64))
        assert attestation.status_code==200 and attestation.json()["human_authorship_attested"] is False
        assert attestation.json()["unique_correct"]==1
        assert sha256(root/"cases.json")==json.loads((root/"manifest.json").read_text())["cases_sha256"]


def test_human_admission_does_not_relabel_external_data_as_human(tmp_path):
    from hydra.training.human_certification import freeze
    source=tmp_path/"source.jsonl"
    source.write_text("".join(json.dumps(dict(id=str(i),prompt=f"Pregunta {i}",expected="referencia",
        authorship="synthetic",review_status="approved",author="IA",reviewer="Persona",training_allowed=False,kind="literal"))+"\n"
        for i in range(100)),encoding="utf-8")
    with pytest.raises(ValueError,match="authorship"):
        freeze(source,tmp_path/"out",[])
