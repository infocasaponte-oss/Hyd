# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from pathlib import Path

import pytest

from hydra.training.instruction_corpus_v6 import build
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256
from hydra.workers.reasoner import requested_json_schema
from hydra.training.corpus_integrity import validate_parent_replay


def test_replay_preflight_rejects_changed_accents_even_when_child_hash_is_recomputed(tmp_path):
    parent=tmp_path/"parent"
    child=tmp_path/"child"
    parent.mkdir()
    child.mkdir()
    row=dict(id="1",messages=[dict(role="user",content="Petición de evaluación")])
    path=parent/"train.jsonl"
    path.write_text(json.dumps(row,ensure_ascii=False)+"\n",encoding="utf-8")
    (parent/"manifest.json").write_text(json.dumps(dict(files={path.name:dict(sha256=sha256(path))})),encoding="utf-8")
    manifest=dict(parent_manifest_sha256=sha256(parent/"manifest.json"))
    (child/"train.jsonl").write_bytes(path.read_bytes())
    validate_parent_replay(child,manifest)
    changed=path.read_text(encoding="cp1252")
    (child/"train.jsonl").write_text(changed,encoding="utf-8")
    with pytest.raises(ValueError,match="inherited corpus rows changed"):
        validate_parent_replay(child,manifest)


def test_explicit_serialization_contract_without_json_word_is_typed_not_answer_encoded():
    prompt="La ficha 77193 tiene activación apagado. Serializa solo las claves id y activo; convierte la activación en true o false."
    messages=[dict(role="user",content=prompt)]
    assert requested_json_schema(messages) is None
    schema=requested_json_schema(messages,True)
    assert schema["required"]==["id","activo"]
    assert schema["properties"]["activo"]=={"type":"boolean"}
    assert "77193" not in json.dumps(schema)
    assert "const" not in json.dumps(schema)
    assert requested_json_schema([dict(role="user",content=prompt+" Conserva activo como texto.")],True) is None


def test_paraphrased_two_property_contract_is_closed_without_hardcoding_values():
    prompt="Conserva el número 714 bajo id y normaliza el estado encendido bajo activo. Produce un objeto con dos propiedades: id entero y activo lógico."
    schema=requested_json_schema([dict(role="user",content=prompt)],True)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["activo"]=={"type":"boolean"}
    assert "714" not in json.dumps(schema) and "const" not in json.dumps(schema)
    assert requested_json_schema([dict(role="user",content=prompt+" Explica cómo lo haces.")],True) is None
    assert requested_json_schema([dict(role="user",content=prompt+" Sin explicación.")],True)==schema
    assert requested_json_schema([dict(role="user",content=prompt+" Omite toda explicación.")],True)==schema


@pytest.mark.skipif(not Path("data/hydra-instruction-v5/manifest.json").exists(), reason="requires local frozen corpus")
def test_v6_keeps_known_tests_and_wording_families_out_of_training(tmp_path):
    manifest = build(tmp_path / "v6")
    assert manifest["new_synthetic_examples"] == 320
    assert not manifest["human_reviewed"]
    assert manifest["files"]["train.jsonl"]["examples"] == 836
    assert sha256(tmp_path / "v6/test.jsonl") == sha256(Path("data/hydra-instruction-v5/test.jsonl"))
    for split in ("train","validation","calibration"):
        old=[json.loads(line) for line in Path(f"data/hydra-instruction-v5/{split}.jsonl").read_text(encoding="utf-8").splitlines()]
        new=[json.loads(line) for line in (tmp_path/f"v6/{split}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert new[:len(old)]==old
    groups = {}
    prompts = []
    for split in ("train", "validation", "calibration", "test"):
        rows = [json.loads(line) for line in (tmp_path / f"v6/{split}.jsonl").read_text(encoding="utf-8").splitlines()]
        prompts.extend(normalized(row["messages"][1]["content"]) for row in rows)
        new = [row for row in rows if row["id"].startswith("v6-")]
        groups[split] = {row["wording_family"] for row in new}
        for row in new:
            answer = json.loads(row["messages"][-1]["content"])
            assert set(answer) == {"id", "activo"}
            assert type(answer["id"]) is int and type(answer["activo"]) is bool
            assert row["training_allowed"] == (split == "train")
            assert "id" in row["messages"][1]["content"] and "activo" in row["messages"][1]["content"]
    assert len(prompts) == len(set(prompts))
    assert not groups["train"] & (groups["validation"] | groups["calibration"])
    assert not groups["validation"] & groups["calibration"]


def test_v6_review_cannot_accept_v5_votes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hydra.api import evaluation_routes as routes

    corpus = tmp_path / "data"
    corpus.mkdir()
    (corpus / "cases.json").write_text(json.dumps([dict(id=1, prompt="Pregunta", expected_response="Referencia")]))
    digest = sha256(corpus / "cases.json")
    (corpus / "manifest.json").write_text(json.dumps(dict(cases_sha256=digest, duplicate_groups=[])))
    evidence = tmp_path / "docs/evidence"
    evidence.mkdir(parents=True)
    (evidence / "external-evaluation-v6.json").write_text(json.dumps(dict(
        artifact_sha256="6" * 64, dataset_sha256=digest, cases=[dict(id=1, output="Respuesta")]
    )))
    (tmp_path / "runtime").mkdir()
    monkeypatch.setattr(routes, "ROOT", tmp_path)
    monkeypatch.setattr(routes, "DATA", corpus)
    app = FastAPI()
    routes.register(app, [], 6)
    with TestClient(app) as client:
        assert client.get("/hydra/v1/evaluation/cases").json()["candidate_version"] == 6
        body = dict(case_id=1, decision="correct", reviewer="Persona", artifact_sha256="5" * 64)
        assert client.post("/hydra/v1/evaluation/review", json=body).status_code == 409
        assert not (tmp_path / "runtime/external-evaluation-v6-reviews.json").exists()
