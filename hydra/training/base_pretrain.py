# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Base pretraining from scratch (stage 0: ~30M parameters on one consumer GPU).

Standard Llama architecture (RMSNorm, SwiGLU, RoPE, GQA, tied embeddings) so llama.cpp converts it
unchanged; deep-and-thin shape for sub-billion models; AdamW with a warmup-stable-decay schedule
(continuable), bf16 autocast, no weight decay on embeddings and norms. Data is the licence-checked
``base_corpus`` tokenised with the HYDRA tokenizer into uint16 token files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from hydra.training.base_corpus import canonical_sha256, iter_texts
from hydra.training.base_corpus import file_sha256
from hydra.core.atomic import write_text_atomic


@dataclass
class ModelShape:
    hidden_size: int = 320
    num_hidden_layers: int = 18
    num_attention_heads: int = 5
    num_key_value_heads: int = 1
    intermediate_size: int = 896
    max_position_embeddings: int = 1024


SHAPES = {
    "30m": ModelShape(),
    "125m": ModelShape(hidden_size=576, num_hidden_layers=30, num_attention_heads=9,
                       num_key_value_heads=3, intermediate_size=1536, max_position_embeddings=1024),
}


@dataclass
class TrainPlan:
    seq_len: int = 1024
    micro_batch: int = 4  # 16 overflowed 8 GiB (32k-vocab fp32 logits) into shared memory: 13x slower
    accumulation: int = 16
    learning_rate: float = 2e-3
    min_lr_ratio: float = 0.1
    warmup_fraction: float = 0.02
    decay_fraction: float = 0.2
    weight_decay: float = 0.1
    epochs: float = 1.0
    eval_every: int = 250
    eval_batches: int = 50
    seed: int = 42
    gradient_checkpointing: bool = False
    checkpoint_every: int = 250
    loss_chunk_tokens: int = 256


PLANS = {"30m": TrainPlan(), "125m": TrainPlan(micro_batch=8, accumulation=8, gradient_checkpointing=True)}


def tokenize(corpus: Path, tokenizer_dir: Path, output: Path) -> dict:
    """uint16 token files with EOS between documents; vocab must fit in 16 bits."""
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(tokenizer_dir / "tokenizer.model"))
    if sp.get_piece_size() > 65535:
        raise ValueError("vocabulary does not fit uint16")
    output.mkdir(parents=True, exist_ok=True)
    counts = {}
    for split in ("train", "validation"):
        path = output / f"{split}.bin"
        total = 0
        with path.open("wb") as stream:
            batch: list[str] = []
            for text in iter_texts(corpus, split):
                batch.append(text)
                if len(batch) == 256:
                    total += _write(stream, sp, batch)
                    batch = []
            if batch:
                total += _write(stream, sp, batch)
        counts[split] = {"tokens": total, "sha256": file_sha256(path)}
    return counts


def _write(stream, sp, texts: list[str]) -> int:
    ids = []
    for encoded in sp.encode(texts):
        # BOS + document + EOS: the exported tokenizer adds BOS at inference, so training sees it too.
        ids.append(sp.bos_id())
        ids.extend(encoded)
        ids.append(sp.eos_id())
    np.asarray(ids, dtype=np.uint16).tofile(stream)
    return len(ids)


def verify_tokens(data_dir: Path, corpus: Path, tokenizer_dir: Path) -> dict:
    """Refuse cached token files that no longer match their manifest, the corpus or the tokenizer."""
    manifest = json.loads((data_dir / "tokens-manifest.json").read_text(encoding="utf-8"))
    for split in ("train", "validation"):
        if file_sha256(data_dir / f"{split}.bin") != manifest[split]["sha256"]:
            raise ValueError(f"cached {split}.bin does not match tokens-manifest.json")
    if manifest["tokenizer_sha256"] != hashlib.sha256((tokenizer_dir / "tokenizer.model").read_bytes()).hexdigest():
        raise ValueError("cached tokens were produced with a different tokenizer")
    if manifest["corpus_manifest_sha256"] not in {canonical_sha256(corpus / "manifest.json"),
                                                  hashlib.sha256((corpus / "manifest.json").read_bytes()).hexdigest()}:
        raise ValueError("cached tokens were produced from a different corpus")
    return manifest


def wsd_lr(step: int, total: int, plan: TrainPlan) -> float:
    """Warmup -> stable -> linear decay to min_lr_ratio (stable phase allows continuing later)."""
    warmup = max(1, int(total * plan.warmup_fraction))
    decay_start = int(total * (1 - plan.decay_fraction))
    if step < warmup:
        return plan.learning_rate * (step + 1) / warmup
    if step < decay_start:
        return plan.learning_rate
    progress = (step - decay_start + 1) / max(1, total - decay_start)  # the last step lands on the minimum
    return plan.learning_rate * (1 - (1 - plan.min_lr_ratio) * min(1.0, progress))


def build_model(vocab_size: int, shape: ModelShape, tokenizer_dir: Path):
    from transformers import LlamaConfig, LlamaForCausalLM

    import sentencepiece as spm
    sp = spm.SentencePieceProcessor(model_file=str(tokenizer_dir / "tokenizer.model"))
    config = LlamaConfig(vocab_size=vocab_size, tie_word_embeddings=True, rms_norm_eps=1e-5, rope_theta=10000.0,
                         bos_token_id=sp.bos_id(), eos_token_id=sp.eos_id(), pad_token_id=sp.pad_id(),
                         attention_bias=False, mlp_bias=False, **asdict(shape))
    return LlamaForCausalLM(config)


def param_groups(model, weight_decay: float):
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (no_decay if p.ndim < 2 or "embed" in name or "norm" in name else decay).append(p)
    return [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}]


def batches(tokens: np.ndarray, seq_len: int, micro_batch: int, rng: np.random.Generator):
    high = len(tokens) - seq_len - 1
    if high <= 0:
        raise ValueError("token partition is shorter than the training sequence")
    import torch
    while True:
        starts = rng.integers(0, high, size=micro_batch)
        chunk = np.stack([tokens[s:s + seq_len + 1] for s in starts]).astype(np.int64)
        yield torch.from_numpy(chunk[:, :-1]), torch.from_numpy(chunk[:, 1:])


def language_loss(logits, labels, chunk_tokens: int = 256):
    """Recompute chunked fp32 CE in backward instead of retaining full-vocabulary fp32 logits."""
    import torch
    from torch.utils.checkpoint import checkpoint
    flat = logits.reshape(-1, logits.size(-1))
    targets = labels.reshape(-1)
    def loss_chunk(z, y):
        return torch.nn.functional.cross_entropy(z.float(), y, reduction="sum")
    losses = []
    for start in range(0, len(targets), chunk_tokens):
        z, y = flat[start:start + chunk_tokens], targets[start:start + chunk_tokens]
        losses.append(checkpoint(loss_chunk, z, y, use_reentrant=False) if z.requires_grad else loss_chunk(z, y))
    return torch.stack(losses).sum() / len(targets)


def save_resume(path: Path, payload: dict):
    import torch
    fd, temporary = tempfile.mkstemp(prefix=".resume-", suffix=".pt", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            torch.save(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        marker = path.with_suffix(".json")
        # Preserve the preceding committed point across the two-file commit.
        # A crash after replacing weights but before metadata can fall back.
        if path.exists() and marker.exists():
            old = json.loads(marker.read_text(encoding="utf-8"))
            if old["sha256"] == file_sha256(path):
                previous = path.with_name("resume-previous.pt")
                write_text_atomic(previous.with_suffix(".json"), json.dumps(old, indent=2))
                os.replace(path, previous)
        os.replace(temporary, path)
        write_text_atomic(path.with_suffix(".json"), json.dumps({"sha256": file_sha256(path),
                         "step": payload["step"], "identity": payload["identity"]}, indent=2))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_resume(folder: Path, identity: dict, device):
    import torch
    for filename in ("resume.pt", "resume-previous.pt"):
        path = folder / filename
        if not path.exists() or not path.with_suffix(".json").exists():
            continue
        marker = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if marker["identity"] != identity or marker["sha256"] != file_sha256(path):
            continue
        payload = torch.load(path, map_location=device, weights_only=True)
        if payload["identity"] == identity and payload["step"] == marker["step"]:
            return payload
    raise ValueError("no valid resume point matches the training identity and checksum")


def evaluate(model, tokens: np.ndarray, plan: TrainPlan, device) -> float:
    import torch

    rng = np.random.default_rng(plan.seed + 1)
    losses = []
    model.eval()
    with torch.no_grad():
        for _, (x, y) in zip(range(plan.eval_batches), batches(tokens, plan.seq_len, plan.micro_batch, rng)):
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(input_ids=x.to(device)).logits
            losses.append(language_loss(logits, y.to(device), plan.loss_chunk_tokens).item())
    model.train()
    return float(np.mean(losses))


def train(data_dir: Path, tokenizer_dir: Path, output: Path, shape: ModelShape, plan: TrainPlan,
          max_steps: int | None = None, device: str | None = None, stage: int = 0,
          resume: bool = False, stop_after: int | None = None) -> dict:
    import torch

    if output.exists() and not resume:
        raise FileExistsError("use a new versioned model directory")
    if resume and not any((output / name).is_file() for name in ("resume.pt", "resume-previous.pt")):
        raise FileNotFoundError("no completed pretraining resume point")
    if (min(plan.seq_len, plan.micro_batch, plan.accumulation, plan.eval_every, plan.eval_batches,
            plan.checkpoint_every, plan.loss_chunk_tokens) <= 0 or plan.seq_len > shape.max_position_embeddings
            or max_steps is not None and max_steps <= 0 or stop_after is not None and stop_after <= 0):
        raise ValueError("invalid pretraining sizes or step bounds")
    output.mkdir(parents=True, exist_ok=resume)
    torch.manual_seed(plan.seed)
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    train_tokens = np.memmap(data_dir / "train.bin", dtype=np.uint16, mode="r")
    val_tokens = np.memmap(data_dir / "validation.bin", dtype=np.uint16, mode="r")
    import sentencepiece as spm
    vocab = spm.SentencePieceProcessor(model_file=str(tokenizer_dir / "tokenizer.model")).get_piece_size()
    model = build_model(vocab, shape, tokenizer_dir).to(device)
    if plan.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
    parameters = sum(p.numel() for p in model.parameters())
    tokens_per_step = plan.seq_len * plan.micro_batch * plan.accumulation
    total = max_steps or max(1, int(len(train_tokens) * plan.epochs / tokens_per_step))
    optimizer = torch.optim.AdamW(param_groups(model, plan.weight_decay), lr=plan.learning_rate,
                                  betas=(0.9, 0.95), eps=1e-8, fused=device.type == "cuda")
    stream_rng = np.random.default_rng(plan.seed)
    stream = batches(train_tokens, plan.seq_len, plan.micro_batch, stream_rng)
    history, started = [], time.time()
    identity = {"shape": asdict(shape), "plan": asdict(plan), "total_steps": total, "stage": stage,
                "tokens_manifest_sha256": file_sha256(data_dir / "tokens-manifest.json"),
                "tokenizer_sha256": file_sha256(tokenizer_dir / "tokenizer.model"), "device_type": device.type}
    first_step, prior_runtime = 0, 0.0
    if resume:
        payload = load_resume(output, identity, device)
        model.load_state_dict(payload["model"])
        optimizer.load_state_dict(payload["optimizer"])
        first_step, history, prior_runtime = payload["step"], payload["history"], payload["runtime_s"]
        stream_rng.bit_generator.state = payload["numpy_rng"]
        torch.set_rng_state(payload["torch_rng"].cpu())
        if device.type == "cuda":
            torch.cuda.set_rng_state_all([state.cpu() for state in payload["cuda_rng"]])
    log = (output / "train.log").open("a" if resume else "w", encoding="utf-8")
    def checkpoint_at(step):
        save_resume(output / "resume.pt", {"identity": identity, "step": step,
            "model": model.state_dict(), "optimizer": optimizer.state_dict(), "history": history,
            "numpy_rng": stream_rng.bit_generator.state, "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
            "runtime_s": prior_runtime + time.time() - started})
    for step in range(first_step, total):
        for group in optimizer.param_groups:
            group["lr"] = wsd_lr(step, total, plan)
        loss_sum = 0.0
        for _ in range(plan.accumulation):
            x, y = next(stream)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(input_ids=x.to(device)).logits
            loss = language_loss(logits, y.to(device), plan.loss_chunk_tokens)
            (loss / plan.accumulation).backward()
            loss_sum += loss.item() / plan.accumulation
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        if step % 10 == 0:
            log.write(json.dumps({"step": step, "loss": round(loss_sum, 4), "lr": optimizer.param_groups[0]["lr"],
                                  "elapsed_s": round(time.time() - started, 1)}) + "\n")
            log.flush()
        if (step + 1) % plan.eval_every == 0 or step + 1 == total:
            val = evaluate(model, val_tokens, plan, device)
            history.append({"step": step + 1, "train_loss": round(loss_sum, 4), "val_loss": round(val, 4),
                            "val_perplexity": round(math.exp(val), 2)})
            log.write(json.dumps(history[-1]) + "\n")
            log.flush()
        if (step + 1) % plan.checkpoint_every == 0 or step + 1 == total or step + 1 == stop_after:
            checkpoint_at(step + 1)
        if step + 1 == stop_after and step + 1 < total:
            log.close()
            return {"status": "INTERRUPTED_AT_CHECKPOINT", "steps": step + 1, "total_steps": total}
    log.close()
    final = output / "final"
    model.save_pretrained(final, safe_serialization=True)
    for name in ("tokenizer.model", "tokenizer_config.json", "special_tokens_map.json"):
        shutil.copy2(tokenizer_dir / name, final / name)
    weights = final / "model.safetensors"
    report = {"kind": "hydra-base", "stage": stage, "approved": False, "parameters": parameters, "shape": asdict(shape),
              "plan": asdict(plan), "steps": total, "tokens_seen": total * tokens_per_step,
              "train_tokens": int(len(train_tokens)), "device": str(device),
              "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
              "peak_allocated_bytes": torch.cuda.max_memory_allocated() if device.type == "cuda" else 0,
              "runtime_s": round(prior_runtime + time.time() - started, 1), "history": history,
              "weights_sha256": file_sha256(weights),
              "tokenizer_sha256": hashlib.sha256((tokenizer_dir / "tokenizer.model").read_bytes()).hexdigest(),
              "data_manifest": json.loads((data_dir / "tokens-manifest.json").read_text(encoding="utf-8")),
              "license": "HYDRA Base proprietary (docs/legal/LICENCIA_PESOS_HYDRA_BASE.md); weights never published"}
    (output / "build-manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/hydra-base-corpus-v0"))
    parser.add_argument("--tokenizer", type=Path, default=Path("models/hydra-base-tokenizer-v0"))
    parser.add_argument("--data", type=Path, default=Path("data/hydra-base-tokens-v0"))
    parser.add_argument("--output", type=Path, default=Path("models/hydra-base-v0-30m"))
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--tokenize-only", action="store_true")
    parser.add_argument("--shape", choices=sorted(SHAPES), default="30m")
    parser.add_argument("--stage", type=int, choices=(0, 1), default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not (args.data / "tokens-manifest.json").exists():
        counts = tokenize(args.corpus, args.tokenizer, args.data)
        manifest = {"corpus_manifest_sha256": canonical_sha256(args.corpus / "manifest.json"),
                    "tokenizer_sha256": hashlib.sha256((args.tokenizer / "tokenizer.model").read_bytes()).hexdigest(),
                    "document_framing": "bos+document+eos", **counts}
        (args.data / "tokens-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
                                                        newline="\n")
        print(json.dumps(manifest, indent=2))
    else:
        verify_tokens(args.data, args.corpus, args.tokenizer)
    if not args.tokenize_only:
        result = train(args.data, args.tokenizer, args.output, SHAPES[args.shape], PLANS[args.shape], args.max_steps,
                       stage=args.stage, resume=args.resume)
        print(json.dumps({k: result[k] for k in ("parameters", "steps", "tokens_seen", "runtime_s", "history")}, indent=2))
