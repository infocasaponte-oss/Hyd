# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
import math

import pytest

from hydra.training.instruction_corpus_v4 import build, normalized
from hydra.training.generation_reliability import check, same_json, wilson
from hydra.training.vllm_calibration import fit, metrics, probabilities
from hydra.workers.reasoner import requested_json_schema

# data/ is gitignored: corpus builds need the local data/hydra-corpus-v1/train.jsonl
LOCAL_DATA = __import__("pathlib").Path("data/hydra-corpus-v1/train.jsonl")
needs_local_data = pytest.mark.skipif(not LOCAL_DATA.exists(), reason=f"{LOCAL_DATA} is not in this checkout")


@pytest.mark.parametrize("native", [True, False])
async def test_reasoner_passes_json_schema_only_to_capable_profiles(native):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from hydra.core.contracts import ModelResponse
    from hydra.registry.models import ModelProfile, ModelQuirks
    from hydra.workers.reasoner import ReasonerWorker

    invoke = AsyncMock(return_value=ModelResponse(model_id="candidate",content="{}",latency_ms=1))
    worker = ReasonerWorker(SimpleNamespace(invoke=invoke))
    worker.build_messages = lambda *args, **kwargs: [{"role":"user","content":"Devuelve solo JSON válido"}]
    ctx = SimpleNamespace(route=None,emit=AsyncMock(),failed_models=set())
    model = ModelProfile(id="candidate",provider="mock",quirks=ModelQuirks(native_json_schema=native))
    await worker.execute(ctx,model)
    request = invoke.call_args.args[2]
    assert bool(request.response_schema) is native


@pytest.mark.parametrize("prompt", ["Devuelve solo JSON válido", "Return only JSON", "Responde únicamente JSON", "JSON only please",
    "Devuélveme un JSON con tres claves", "Genera un JSON", "JSON con 'task'='eval'"])
def test_explicit_json_contract(prompt):
    assert requested_json_schema([{"role":"user","content":prompt}])["anyOf"][0] == {"type":"object"}


@pytest.mark.parametrize("prompt", ["Explica qué es JSON", "No quiero solo JSON", "No uses JSON", "Habla de Python"])
def test_json_discussion_does_not_force_format(prompt):
    assert requested_json_schema([{"role":"user","content":prompt}]) is None


def test_state_contract_is_opt_in_and_contains_no_expected_values():
    messages=[{"role":"user","content":"Convierte este registro a un objeto JSON con las mismas claves: id: 98765; activo: no. No uses Markdown."}]
    assert requested_json_schema(messages) is None
    schema=requested_json_schema(messages,typed_state_json=True)
    assert schema["properties"]["activo"]=={"type":"boolean"}
    assert "98765" not in json.dumps(schema) and "const" not in json.dumps(schema)
    assert requested_json_schema([{"role":"user","content":"Explica qué significa activo: no"}],True) is None
    assert requested_json_schema([{"role":"user","content":messages[0]["content"]+" Conserva activo como texto."}],True) is None
    extra=messages[0]["content"].replace("activo: no.","activo: no; nombre: Ana.")
    assert requested_json_schema([{"role":"user","content":extra}],True) is None


@needs_local_data
def test_500_unique_and_partitioned_with_frozen_test(tmp_path):
    root = tmp_path / "corpus"
    manifest = build(root)
    assert manifest["synthetic_paraphrases"] == 500
    assert manifest["human_reviewed"] is False
    rows = {s:[json.loads(line) for line in (root/f"{s}.jsonl").read_text(encoding="utf-8").splitlines()]
            for s in ("train", "validation", "calibration", "test")}
    generated = [r for group in rows.values() for r in group if r["id"].startswith("v4-")]
    assert len(generated) == len({normalized(r["messages"][1]["content"]) for r in generated}) == 500
    families = [{r["wording_family"] for r in rows[s] if "wording_family" in r} for s in ("train", "validation", "calibration")]
    assert not families[0] & families[1] and not families[0] & families[2] and not families[1] & families[2]
    assert all(not r["training_allowed"] for s in ("validation", "calibration") for r in rows[s])
    assert manifest["files"]["test.jsonl"]["sha256"] == manifest["frozen_test_sha256"]
    assert len(rows["train"]) == 492
    for row in generated:
        assert check(row, row["messages"][-1]["content"])
    with pytest.raises(FileExistsError):
        build(root)


def test_json_does_not_confuse_booleans_numbers_or_arrays():
    assert not same_json({"x":True}, {"x":1})
    assert not same_json([True], [1])
    assert not same_json([1], [1,2])
    assert same_json({"x":[1,False]}, {"x":[1,False]})


def test_small_perfect_calibration_is_not_certification():
    assert wilson(10,10)[0] < .90
    assert wilson(100,100)[0] > .90
    with pytest.raises(ValueError):
        wilson(0,0)


def test_temperature_fit_improves_overconfidence_without_changing_decisions():
    rows = [dict(id=str(i), split="calibration", expected="a" if i < 7 else "b",
                 logprobs_mode="raw_logprobs", candidate_logprobs={"a":0.,"b":-8.}) for i in range(10)]
    temperature = fit(rows,["a","b"])
    assert temperature > 1
    assert metrics(rows,temperature)["nll"] < metrics(rows,1)["nll"]
    assert metrics(rows,temperature)["accuracy"] == metrics(rows,1)["accuracy"] == .7
    assert sum(probabilities({"a":-1000,"b":-1001}).values()) == pytest.approx(1)


@pytest.mark.parametrize("change", [dict(split="test"), dict(logprobs_mode="processed_logprobs"),
    dict(candidate_logprobs={"a":0}), dict(candidate_logprobs={"a":0,"b":math.nan}), dict(expected="unknown")])
def test_vllm_rejects_leakage_and_truncated_or_invalid_scores(change):
    row = dict(id="case", split="calibration", expected="a", logprobs_mode="raw_logprobs", candidate_logprobs={"a":0,"b":-2})
    row.update(change)
    with pytest.raises(ValueError):
        fit([row],["a","b"])
