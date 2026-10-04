# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from types import SimpleNamespace

import pytest

from hydra.evals.engine import CaseResult, EvalReport, SuiteResult
from hydra.training.lab import EvalArena, TrainingOrchestrator, TrainingRecipe
from hydra.model_factory.train_lora import normalize_job
from hydra.training.verified_corpus import build


def report(name, score=1.0):
    return EvalReport(target=name, overall=score,
                      suites={"coding": SuiteResult(suite="coding",score=score,passed=1,total=1,mean_latency_ms=10)},
                      cases=[CaseResult(id="one",suite="coding",passed=True,score=score,latency_ms=10)])


def test_arena_accepts_actual_evaluator_contract():
    result = EvalArena().compare(report("candidate"), report("base"))
    assert result.passed and result.candidate == "candidate"
    assert result.metrics["latency_ms"] == 10
    assert not EvalArena().compare(report("candidate", 0.5), report("base")).passed


def test_arena_rejects_missing_evidence():
    result = EvalArena().compare(EvalReport(target="empty"), EvalReport(target="base"))
    assert not result.passed and "missing evaluation evidence" in result.reasons


@pytest.mark.parametrize("evaluation", [None, {}, {"passed": "false"}, {"passed": False}])
async def test_training_without_explicit_evaluation_is_rejected(runtime, tmp_path, evaluation):
    train = tmp_path / "train.jsonl"
    train.write_text('{}\n')
    runtime.datasets = SimpleNamespace(build=lambda spec: SimpleNamespace(
        id="data", files=["train.jsonl"], path=str(tmp_path), splits={"train":1}, examples=1,record_ids_hash="abc"))
    class Backend:
        def choose(self, recipe): return "test"
        async def train(self, run, train, valid, work):
            (work / "adapter").mkdir()
            (work / "adapter" / "weights").write_bytes(b"test")
            return {}
    async def evaluate(run): return evaluation
    run = await TrainingOrchestrator(runtime, Backend()).run(
        TrainingRecipe(name="test",base_model="test",dataset_id="data"),
        eval_fn=evaluate if evaluation is not None else None)
    assert run.status.value == "REJECTED"
    assert run.error == "evaluation missing or did not explicitly pass"


def test_lab_recipe_maps_to_peft_job():
    job = normalize_job({"method":"lora", "train":"train.jsonl", "lora_rank":16,"lora_alpha":32,"max_length":256})
    assert job["dataset"] == "train.jsonl" and job["r"] == 16
    assert job["alpha"] == 32 and job["max_seq_length"] == 256


def test_verified_corpus_is_reproducible_and_families_are_disjoint(tmp_path):
    a = build(tmp_path / "a", 3)
    b = build(tmp_path / "b", 3)
    assert a == b
    families = [set(v) for v in a["families"].values()]
    assert not any(x & y for i,x in enumerate(families) for y in families[i+1:])
    assert a["files"]["train.jsonl"]["examples"] == 18


def test_training_reader_excludes_heterogeneous_verification_metadata(tmp_path):
    from hydra.model_factory.train_lora import message_rows
    build(tmp_path, 2)
    rows = list(message_rows(str(tmp_path / "train.jsonl")))
    assert len(rows) == 12
    assert all(set(row) == {"messages"} for row in rows)
def test_classifier_reads_corpus_parquet_like_jsonl(tmp_path):
    import json
    import pytest

    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    from hydra.training.specialists import _examples

    rows = [{"input": {"query": "clasifica código español"}, "output": {"task_type": "coding"}}]
    jsonl = tmp_path / "train.jsonl"
    jsonl.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")
    parquet = tmp_path / "train.parquet"
    pq.write_table(pa.Table.from_pylist([
        {k: json.dumps(v, ensure_ascii=False) for k, v in row.items()} for row in rows]), parquet)
    assert _examples(parquet) == _examples(jsonl) == (["clasifica código español"], ["coding"])
