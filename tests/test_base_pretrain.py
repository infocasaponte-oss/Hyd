# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import numpy as np
import pytest

from hydra.training import base_corpus as bc
from hydra.training import base_pretrain as bp


def test_wsd_schedule_warms_up_holds_and_decays():
    plan = bp.TrainPlan(learning_rate=1.0, warmup_fraction=0.1, decay_fraction=0.2, min_lr_ratio=0.1)
    lrs = [bp.wsd_lr(step, 100, plan) for step in range(100)]
    assert lrs[0] < lrs[9] == 1.0 and lrs[50] == 1.0 and lrs[79] == 1.0
    assert lrs[99] == pytest.approx(0.1, abs=0.01) and all(a >= b for a, b in zip(lrs[80:], lrs[81:]))


def test_no_weight_decay_on_embeddings_and_norms():
    pytest.importorskip("torch")
    pytest.importorskip("transformers")  # training extras are not installed in CI
    from transformers import LlamaConfig, LlamaForCausalLM

    model = LlamaForCausalLM(LlamaConfig(vocab_size=64, hidden_size=16, intermediate_size=32, num_hidden_layers=1,
                                         num_attention_heads=2, num_key_value_heads=1, tie_word_embeddings=True))
    decay, no_decay = bp.param_groups(model, 0.1)
    assert all(p.ndim >= 2 for p in decay["params"]) and no_decay["weight_decay"] == 0.0
    names = {id(p): n for n, p in model.named_parameters()}
    assert any("embed" in names[id(p)] for p in no_decay["params"])


def test_tokenize_and_train_a_tiny_model_end_to_end(tmp_path):
    spm = pytest.importorskip("sentencepiece")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    sentences = [f"El artículo {i} regula la materia número {i * 7} de la ley de prueba." for i in range(400)]
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    import gzip
    for split, rows in (("train", sentences[:380]), ("validation", sentences[380:])):
        with gzip.open(corpus / f"{split}-00000.jsonl.gz", "wt", encoding="utf-8") as stream:
            for text in rows:
                stream.write(json.dumps({"text": text * 3}) + "\n")
    (corpus / "manifest.json").write_text("{}", encoding="utf-8")
    tok = tmp_path / "tok"
    tok.mkdir()
    (tmp_path / "sample.txt").write_text("\n".join(sentences), encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(tmp_path / "sample.txt"), model_prefix=str(tok / "tokenizer"),
                                   model_type="bpe", vocab_size=400, byte_fallback=True, unk_id=0, bos_id=1,
                                   eos_id=2, pad_id=3)
    for name in ("tokenizer_config.json", "special_tokens_map.json"):
        (tok / name).write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    counts = bp.tokenize(corpus, tok, data)
    assert counts["train"]["tokens"] > 0 and counts["validation"]["tokens"] > 0
    tokens = np.fromfile(data / "train.bin", dtype=np.uint16)
    assert tokens.max() < 400
    assert tokens[0] == 1 and (tokens == 1).sum() == (tokens == 2).sum()  # every document is BOS ... EOS
    import hashlib
    manifest = {"corpus_manifest_sha256": bc.canonical_sha256(corpus / "manifest.json"),
                "tokenizer_sha256": hashlib.sha256((tok / "tokenizer.model").read_bytes()).hexdigest(), **counts}
    (data / "tokens-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert bp.verify_tokens(data, corpus, tok)["train"]["tokens"] == counts["train"]["tokens"]
    shape = bp.ModelShape(hidden_size=32, num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
                          intermediate_size=64, max_position_embeddings=64)
    plan = bp.TrainPlan(seq_len=32, micro_batch=4, accumulation=1, eval_every=3, eval_batches=2)
    report = bp.train(data, tok, tmp_path / "model", shape, plan, max_steps=6, device="cpu")
    assert report["steps"] == 6 and len(report["history"]) == 2
    assert report["history"][-1]["val_loss"] < report["history"][0]["val_loss"] + 1.0
    assert (tmp_path / "model" / "final" / "model.safetensors").exists()
    assert (tmp_path / "model" / "final" / "tokenizer.model").exists()
    with pytest.raises(FileExistsError):
        bp.train(data, tok, tmp_path / "model", shape, plan, max_steps=1, device="cpu")
    assert list(bc.iter_texts(corpus, "validation"))


def test_cached_tokens_are_verified(tmp_path):
    import hashlib

    data, corpus, tok = tmp_path / "data", tmp_path / "corpus", tmp_path / "tok"
    for folder in (data, corpus, tok):
        folder.mkdir()
    (corpus / "manifest.json").write_text("{}", encoding="utf-8")
    (tok / "tokenizer.model").write_bytes(b"model-a")
    np.asarray([1, 5, 2], dtype=np.uint16).tofile(data / "train.bin")
    np.asarray([1, 6, 2], dtype=np.uint16).tofile(data / "validation.bin")
    manifest = {"corpus_manifest_sha256": bc.canonical_sha256(corpus / "manifest.json"),
                "tokenizer_sha256": hashlib.sha256(b"model-a").hexdigest(),
                "train": {"sha256": hashlib.sha256((data / "train.bin").read_bytes()).hexdigest()},
                "validation": {"sha256": hashlib.sha256((data / "validation.bin").read_bytes()).hexdigest()}}
    (data / "tokens-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    bp.verify_tokens(data, corpus, tok)
    (tok / "tokenizer.model").write_bytes(b"model-b")
    with pytest.raises(ValueError, match="different tokenizer"):
        bp.verify_tokens(data, corpus, tok)
    (tok / "tokenizer.model").write_bytes(b"model-a")
    np.asarray([1, 5], dtype=np.uint16).tofile(data / "train.bin")  # truncated
    with pytest.raises(ValueError, match="train.bin"):
        bp.verify_tokens(data, corpus, tok)


def test_stage1_shape_is_about_125m_and_keeps_tokens_per_step():
    from dataclasses import asdict

    pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")  # training extras are not installed in CI
    LlamaConfig, LlamaForCausalLM = transformers.LlamaConfig, transformers.LlamaForCausalLM
    shape = bp.SHAPES["125m"]
    model = LlamaForCausalLM(LlamaConfig(vocab_size=32_000, tie_word_embeddings=True, **asdict(shape)))
    assert 120e6 < sum(p.numel() for p in model.parameters()) < 130e6
    for name in ("30m", "125m"):
        plan = bp.PLANS[name]
        assert plan.micro_batch * plan.accumulation * plan.seq_len == 65_536
    assert bp.PLANS["125m"].gradient_checkpointing and not bp.PLANS["30m"].gradient_checkpointing
