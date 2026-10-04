# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import json
import threading
from dataclasses import asdict

import numpy as np
import pytest

from hydra.hyd.corpus import build, make_record, DOMAINS, SPLITS
from hydra.hyd.engine import HydEngine, typed_confidence
from hydra.hyd.model import CandidateRanker
from hydra.hyd.stage1 import ready, verify_corpus, WorkLease, Stage1Plan, run
from hydra.training import base_pretrain as bp
from hydra.training.base_corpus import file_sha256


def test_generated_targets_and_structural_splits(tmp_path):
    manifest = build(tmp_path / "decisions", per_domain=15)
    families = {}
    for split in SPLITS:
        rows = [json.loads(line) for line in (tmp_path / "decisions" / (split + ".jsonl")).read_text(encoding="utf-8").splitlines()]
        families[split] = {row["family"] for row in rows}
        for row in rows:
            assert sum(row["target"].values()) == 1 and row["training_allowed"] == (split == "train")
            state, operation = row["state"], row["oracle"]["operation"]
            target = max(row["target"], key=row["target"].get)
            if operation == "lookup":
                assert row["question"]["criteria"][target] == state[row["oracle"]["field"]]
            elif operation == "cardinality":
                assert int(target) == len(state["entries"])
            elif operation == "substring":
                assert (target == "true") == (row["oracle"]["needle"] in state["document"])
            elif operation in ("lt", "le", "gt", "ge"):
                a, b = state["value"], state["limit"]
                assert (target == "true") == {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[operation]
    for left in SPLITS:
        for right in SPLITS:
            if left != right:
                assert not families[left] & families[right]
    assert manifest["independent_test"] is False
    assert {make_record("lookup", "train", i)["language"] for i in range(3)} == {"gl", "es", "en"}
    assert all(make_record(domain, "test", 1)["oracle"] for domain in DOMAINS)


def test_typed_confidence_semantics():
    assert typed_confidence("choice", {"a": .5, "b": .5}) == 0
    assert typed_confidence("choice", {"a": .8, "b": .2}) == pytest.approx(.6)
    assert typed_confidence("score", {"0": .25, "1": .25, "2": .25, "3": .25}) == 0
    assert typed_confidence("score", {"0": 0, "1": 1, "2": 0}) == 1
    assert typed_confidence("choice", {"only": 1}) == 1


def sealed_corpus(folder):
    folder.mkdir()
    files = {}
    for split in ("train", "validation"):
        path = folder / (split + "-00000.jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            for i in range(30):
                text = f"Documento {split}-{i} con palabras alfa beta gamma y suficiente información pública. " * 4
                stream.write(json.dumps({"text": text, "source": "PleIAs test", "document_id": f"{split}-work-{i}#0",
                                         "license": "public-domain", "sha256": __import__("hashlib").sha256(text.encode()).hexdigest()}) + "\n")
        files[path.name] = {"sha256": file_sha256(path), "documents": 30}
    notice = folder / "THIRD_PARTY_DATA_NOTICE.txt"
    notice.write_text("test notices", encoding="utf-8")
    attributes = folder / "THIRD_PARTY_ATTRIBUTIONS.jsonl.gz"
    with gzip.open(attributes, "wt", encoding="utf-8") as stream:
        stream.write("")
    manifest = {"files": files, "notice_sha256": file_sha256(notice),
                "attributions": {"file": attributes.name, "sha256": file_sha256(attributes)},
                "totals": {"characters": 10000}, "sources": []}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_sealed_corpus_required_and_checksums(tmp_path):
    partial = tmp_path / "partial"
    partial.mkdir()
    assert not ready(partial)
    assert run(Stage1Plan(corpus=str(partial)), tmp_path / "state")["stage"] == "WAITING_FOR_SEALED_CORPUS"
    with pytest.raises(ValueError, match="sealed"):
        verify_corpus(partial)
    corpus = sealed_corpus(tmp_path / "corpus")
    assert ready(corpus) and verify_corpus(corpus)["files"]
    (corpus / "train-00000.jsonl.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_corpus(corpus)


def test_quality_audit_and_default_pretraining_block(tmp_path):
    from hydra.hyd.corpus_quality import audit
    assert Stage1Plan().pretraining_authorized is False
    corpus = sealed_corpus(tmp_path / "corpus")
    report = audit(corpus, tmp_path / "quality")
    assert report["integrity_passed"] and report["documents"] == 60
    assert not report["source_modified"]
    shard = corpus / "train-00000.jsonl.gz"
    with gzip.open(shard, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    rows[0]["text"] += " altered"
    with gzip.open(shard, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    manifest = json.loads((corpus / "manifest.json").read_text())
    manifest["files"][shard.name]["sha256"] = file_sha256(shard)
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    report = audit(corpus, tmp_path / "quality")
    assert not report["integrity_passed"] and report["failures"]["document_hash_mismatch"] == 1


def test_quality_review_is_bound_and_cannot_accept_integrity_failures(tmp_path):
    import hashlib
    from hydra.hyd.corpus_quality import reviewed_warnings
    report = {"integrity_passed": True, "corpus_manifest_sha256": "corpus-a", "warnings": {"ocr": 2}}
    review = {"format": "hyd-corpus-review/1", "status": "APPROVED", "reviewer": "local-review",
              "rationale": "Sampled and checked", "evidence": ["sample-report-sha"],
              "report_sha256": hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              "corpus_manifest_sha256": "corpus-a", "accepted_warnings": {"ocr": 2}}
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert reviewed_warnings(report, str(path))
    report["warnings"]["ocr"] = 3
    assert not reviewed_warnings(report, str(path))
    report["integrity_passed"] = False
    assert not reviewed_warnings(report, str(path))


def test_document_supervision_preserves_licenses_and_work_splits(tmp_path):
    from hydra.hyd.base_decisions import build as bridge
    from hydra.hyd.train_typed import read_partition
    base = sealed_corpus(tmp_path / "base")
    synthetic = tmp_path / "synthetic"
    build(synthetic, per_domain=3)
    output = tmp_path / "supervised"
    manifest = bridge(base, synthetic, output, per_source_split=4)
    all_works = {}
    found_licensed = False
    for split in SPLITS:
        rows = read_partition(output / (split + ".jsonl"), split, allow_licensed=True)
        all_works[split] = {row["family"] for row in rows}
        for row in rows:
            if row["rights"]["license"] == "public-domain":
                found_licensed = True
                assert row["rights"]["source_manifest_sha256"] == manifest["parent_base_corpus_sha256"]
                if row["question"]["type"] == "noul":
                    truth = row["state"]["needle"] in row["state"]["document"]
                    assert row["target"]["true"] == float(truth)
    assert found_licensed
    for left in SPLITS:
        for right in SPLITS:
            if left != right:
                assert not all_works[left] & all_works[right]
    with pytest.raises(ValueError, match="owned"):
        read_partition(output / "train.jsonl", "train")


def test_os_work_lease_prevents_duplicate_writers(tmp_path):
    with WorkLease(tmp_path / "work.lock"):
        with pytest.raises(RuntimeError, match="owns"):
            with WorkLease(tmp_path / "work.lock"):
                pass
    with WorkLease(tmp_path / "work.lock"):
        pass


def test_125m_shape_without_optional_training_dependencies():
    shape = bp.SHAPES["125m"]
    h = shape.hidden_size
    kv_width = shape.num_key_value_heads * (h // shape.num_attention_heads)
    parameters = 32000*h + shape.num_hidden_layers*(2*h*h + 2*h*kv_width + 3*h*shape.intermediate_size + 2*h) + h
    assert parameters == 124635456
    assert asdict(shape)["num_hidden_layers"] == 30
    plan = bp.PLANS["125m"]
    assert plan.gradient_checkpointing and plan.seq_len*plan.micro_batch*plan.accumulation == 65536


def test_chunked_language_loss_matches_dense_value_and_gradient():
    torch = pytest.importorskip("torch")
    torch.manual_seed(4)
    a = torch.randn(2, 8, 17, requires_grad=True)
    b = a.detach().clone().requires_grad_(True)
    labels = torch.randint(0, 17, (2, 8))
    dense = torch.nn.functional.cross_entropy(a.reshape(-1, 17), labels.reshape(-1))
    chunked = bp.language_loss(b, labels, chunk_tokens=3)
    dense.backward()
    chunked.backward()
    assert chunked.item() == pytest.approx(dense.item(), abs=1e-6)
    assert torch.allclose(a.grad, b.grad, atol=1e-7)


def test_resume_falls_back_if_latest_weights_or_metadata_were_interrupted(tmp_path):
    torch = pytest.importorskip("torch")
    identity = {"plan": "test"}
    for step in (1, 2):
        bp.save_resume(tmp_path / "resume.pt", {"identity": identity, "step": step, "x": torch.tensor([step])})
    (tmp_path / "resume.pt").write_bytes(b"interrupted replacement")
    assert bp.load_resume(tmp_path, identity, "cpu")["step"] == 1
    with pytest.raises(ValueError, match="identity"):
        bp.load_resume(tmp_path, {"plan": "different"}, "cpu")


async def test_timeout_retains_capacity_until_worker_finishes():
    from hydra.hyd.controller import HydController, HydBusyError
    controller = HydController.__new__(HydController)
    controller._active = None
    controller._jobs = set()
    controller._capacity = 1
    controller._closed = False
    started, finish = threading.Event(), threading.Event()
    class SlowEngine:
        def decide(self, *args):
            started.set()
            finish.wait(3)
            return {"done": True}
    controller.engine = SlowEngine()
    try:
        with pytest.raises(TimeoutError):
            await controller.decide("", {}, timeout_s=.05)
        assert started.is_set()
        with pytest.raises(HydBusyError):
            await controller.decide("", {})
        finish.set()
        assert await controller._active == {"done": True}
    finally:
        finish.set()
        await controller.close()


def test_pretraining_resume_matches_uninterrupted_weights(tmp_path):
    spm = pytest.importorskip("sentencepiece")
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    corpus = sealed_corpus(tmp_path / "corpus")
    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    sample = tmp_path / "sample.txt"
    sample.write_text("\n".join(f"Documento de entrenamiento número {i} con palabras para aprender." for i in range(80)), encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(sample), model_prefix=str(tokenizer / "tokenizer"), model_type="bpe",
        vocab_size=400, byte_fallback=True, unk_id=0, bos_id=1, eos_id=2, pad_id=3, minloglevel=2)
    for name in ("tokenizer_config.json", "special_tokens_map.json"):
        (tokenizer / name).write_text("{}")
    tokens = tmp_path / "tokens"
    counts = bp.tokenize(corpus, tokenizer, tokens)
    (tokens / "tokens-manifest.json").write_text(json.dumps(counts))
    shape = bp.ModelShape(hidden_size=16, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                          intermediate_size=32, max_position_embeddings=32)
    plan = bp.TrainPlan(seq_len=16, micro_batch=2, accumulation=1, eval_every=2, eval_batches=1,
                        checkpoint_every=2, loss_chunk_tokens=8)
    bp.train(tokens, tokenizer, tmp_path / "full", shape, plan, max_steps=4, device="cpu")
    interrupted = bp.train(tokens, tokenizer, tmp_path / "resumed", shape, plan, max_steps=4, device="cpu", stop_after=2)
    assert interrupted["status"] == "INTERRUPTED_AT_CHECKPOINT"
    bp.train(tokens, tokenizer, tmp_path / "resumed", shape, plan, max_steps=4, device="cpu", resume=True)
    from safetensors.torch import load_file
    full, resumed = load_file(tmp_path / "full/final/model.safetensors"), load_file(tmp_path / "resumed/final/model.safetensors")
    assert full.keys() == resumed.keys()
    assert all(torch.equal(full[key], resumed[key]) for key in full)


def test_invalid_plan_and_input_budget_fail_closed():
    engine = HydEngine(CandidateRanker())
    with pytest.raises(ValueError, match="budget"):
        engine.admit("", {str(i): {"type": "choice", "criteria": {"a": "x" * 2000}} for i in range(64)})
    with pytest.raises(ValueError, match="shorter"):
        next(bp.batches(np.arange(8), seq_len=8, micro_batch=1, rng=np.random.default_rng()))


def test_contextual_training_loading_and_isolation(tmp_path):
    spm = pytest.importorskip("sentencepiece")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM
    from hydra.training.base_tokenizer import write_hf_files
    from hydra.hyd.train_neural import train
    from hydra.hyd.controller import HydController
    from hydra.hyd.neural import ContextRanker
    base = tmp_path / "base/final"
    base.mkdir(parents=True)
    samples = tmp_path / "sample.txt"
    samples.write_text("\n".join(f"Un documento número {i} con palabras en español e galego para probar." for i in range(80)), encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(samples), model_prefix=str(base / "tokenizer"), model_type="bpe",
        vocab_size=400, byte_fallback=True, unk_id=0, bos_id=1, eos_id=2, pad_id=3, minloglevel=2)
    write_hf_files(base)
    model = LlamaForCausalLM(LlamaConfig(vocab_size=400, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=1024,
        pad_token_id=3, bos_token_id=1, eos_token_id=2, tie_word_embeddings=True))
    model.save_pretrained(base, safe_serialization=True)
    (base.parent / "build-manifest.json").write_text(json.dumps({"kind": "hydra-base",
        "weights_sha256": file_sha256(base / "model.safetensors"), "tokenizer_sha256": file_sha256(base / "tokenizer.model")}))
    corpus = tmp_path / "corpus"
    build(corpus, per_domain=1)
    report = train(base, corpus, tmp_path / "hyd", epochs=1, max_tokens=1024, device="cpu")
    assert report["authority_enabled"] is False
    hyd = HydController(tmp_path / "hyd/model.json", tmp_path / "hyd/calibration.json")
    assert isinstance(hyd.engine.ranker, ContextRanker)
    row = json.loads((corpus / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    q = row["question"]
    alone = hyd.engine.decide(row["state"], {"q": q})
    shuffled = {**q, "criteria": dict(reversed(list(q["criteria"].items())))}
    together = hyd.engine.decide(row["state"], {"noise": {"type": "noul"}, "q": shuffled})
    assert together["answers"]["q"] == alone["answers"]["q"]
    assert alone["usage"]["input_tokens"] > 0 and alone["generation_tokens"] == 0
    with pytest.raises(ValueError, match="budget"):
        hyd.engine.decide("long document " * 1000, {"q": q})
    (tmp_path / "hyd/head.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        ContextRanker.load(tmp_path / "hyd/model.json")
