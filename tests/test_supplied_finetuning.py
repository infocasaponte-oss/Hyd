# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest
import json

from hydra.model_factory.train_lora import encode_response
from hydra.training.finetuning_v8 import score


def test_json_boolean_cannot_equal_number():
    assert score({"subtype": "json", "answer": '{"ok":true}'}, '{"ok":1}') is False


def test_numeric_substring_is_not_a_correct_answer():
    row = {"category": "razonamiento", "answer": "Pasos.\nRespuesta: 12"}
    assert score(row, "120") is False
    assert score(row, "Respuesta: 12") is True


def test_false_technical_keywords_do_not_certify():
    assert score({"category": "tecnico", "answer": "Una definición"}, "No es vector ni embedding") is None


def test_case_sensitive_instruction():
    assert score({"category": "instrucciones", "answer": "HOLA"}, "hola") is False


def test_pack_identity_is_equivalent_without_substring_matching():
    row = dict(category="razonamiento",subtype="precio_unitario",answer="Respuesta: el pack B")
    assert score(row,"Pack B") is True
    assert score(row,"Pack A") is False
    assert score(row,"Pack B no, Pack A") is False


def test_decimal_equivalence_and_units():
    row = dict(category="razonamiento",subtype="porcentajes",answer="Respuesta: 36,30 €")
    assert score(row,"36.30 euros") is True
    assert score(row,"36.30 km") is False
    assert score(row,"136.30") is False


class Tokenizer:
    eos_token_id = 4
    def __init__(self, full):
        self.full = full

    def apply_chat_template(self, messages, **kwargs):
        return [1, 2] if kwargs.get("add_generation_prompt") else self.full

    def decode(self, ids):
        return "\n" if ids == [0] else "token"


MESSAGES = [{"role": "user", "content": "Pregunta"}, {"role": "assistant", "content": "Respuesta"}]


def test_response_masking_and_prefix_check():
    assert encode_response(Tokenizer([1, 2, 3, 4]), MESSAGES, 4)["labels"] == [-100, -100, 3, 4]
    with pytest.raises(ValueError, match="prefix"):
        encode_response(Tokenizer([1, 9, 3]), MESSAGES, 4)


def test_truncation_is_rejected():
    with pytest.raises(ValueError, match="truncates"):
        encode_response(Tokenizer([1, 2, 3, 4]), MESSAGES, 3)


def test_end_of_turn_is_supervised_and_required():
    with pytest.raises(ValueError, match="end-of-turn"):
        encode_response(Tokenizer([1,2,3]),MESSAGES,4)
    assert encode_response(Tokenizer([1,2,3,4,0]),MESSAGES,5)["labels"] == [-100,-100,3,4,0]


def test_only_bullet_format_does_not_certify_fruits():
    assert score({"subtype": "lista_n", "answer": "- pera\n- uva"}, "- piedra\n- metal") is None


def test_review_completion_uses_unique_cases_and_isolates_v8(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hydra.api import evaluation_routes as routes
    from hydra.training.verified_corpus import sha256
    data = tmp_path/"data"
    data.mkdir()
    rows = [{"id": i, "prompt": "Pregunta", "expected_response": "Respuesta"} for i in (1,2,3)]
    (data/"cases.json").write_text(json.dumps(rows),encoding="utf-8")
    digest = sha256(data/"cases.json")
    (data/"manifest.json").write_text(json.dumps(dict(cases_sha256=digest,duplicate_groups=[[1,3]],unique_cases=2)),encoding="utf-8")
    evidence = tmp_path/"docs/evidence"
    evidence.mkdir(parents=True)
    (tmp_path/"runtime").mkdir()
    (evidence/"external-evaluation-v8.json").write_text(json.dumps(dict(dataset_sha256=digest,artifact_sha256="a"*64,
        cases=[dict(id=i,output="Respuesta") for i in (1,2,3)])),encoding="utf-8")
    prior = tmp_path/"runtime/external-evaluation-v7-reviews.json"
    prior.write_text('{"preserved":true}',encoding="utf-8")
    monkeypatch.setattr(routes,"ROOT",tmp_path)
    monkeypatch.setattr(routes,"DATA",data)
    app = FastAPI()
    routes.register(app,[],candidate_version=8)
    with TestClient(app) as client:
        for i in (1,2):
            response = client.post("/hydra/v1/evaluation/review",json=dict(case_id=i,decision="correct",reviewer="Revisor",artifact_sha256="a"*64))
            assert response.status_code == 200
        saved = response.json()
        assert saved["complete"] is True
        assert saved["unique_reviewed"] == saved["unique_cases"] == 2
    assert prior.read_text(encoding="utf-8") == '{"preserved":true}'
