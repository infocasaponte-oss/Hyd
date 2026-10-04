# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Resumable local pipeline: sealed corpus -> tokenizer -> own base -> Hyd scorer.

The process may wait for the current corpus builder, but never reads partial
shards, interrupts existing GPU processes, publishes weights or promotes a model.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.training.base_corpus import canonical_sha256, file_sha256


@dataclass
class Stage1Plan:
    corpus: str = "data/hydra-base-corpus-v1"
    tokenizer: str = "models/hydra-base-tokenizer-v1"
    tokens: str = "data/hydra-base-tokens-v1"
    base: str = "models/hydra-base-v1-125m"
    synthetic_decisions: str = "data/hyd-typed-corpus-v3"
    decision_corpus: str = "data/hyd-supervised-corpus-v3"
    decision_model: str = "models/hyd-contextual-v3-125m"
    vocab_size: int = 32000
    tokenizer_sample_characters: int = 200000000
    decision_epochs: int = 2
    decision_max_tokens: int = 512
    freeze_encoder: bool = False
    minimum_free_gpu_mib: int = 6656
    pretraining_authorized: bool = False
    quality_review_path: str | None = None


def ready(corpus: Path) -> bool:
    manifest = corpus / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    names = data.get("files", {})
    return (any(name.startswith("train-") for name in names)
            and any(name.startswith("validation-") for name in names)
            and bool(data.get("notice_sha256")) and bool(data.get("attributions", {}).get("sha256")))


def verify_corpus(corpus: Path):
    if not ready(corpus):
        raise ValueError("base corpus is not sealed; wait for the builder's final manifest")
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    if set(manifest["files"]) != {p.name for p in corpus.glob("*-*.jsonl.gz")
                                  if p.name.startswith(("train-", "validation-"))}:
        raise ValueError("base corpus has unmanifested or missing shards")
    for name, metadata in manifest["files"].items():
        if Path(name).name != name or file_sha256(corpus / name) != metadata["sha256"]:
            raise ValueError("base corpus shard checksum mismatch")
    if file_sha256(corpus / "THIRD_PARTY_DATA_NOTICE.txt") != manifest["notice_sha256"]:
        raise ValueError("base corpus attribution notice checksum mismatch")
    attribution = manifest["attributions"]
    if Path(attribution["file"]).name != attribution["file"] or file_sha256(corpus / attribution["file"]) != attribution["sha256"]:
        raise ValueError("base corpus attribution checksum mismatch")
    return manifest


class WorkLease:
    """OS-held lock; process death releases it. A stale PID file never authorizes a second writer."""
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b", buffering=0)
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError("another Hyd pipeline owns this work lease") from None
        return self

    def __exit__(self, *args):
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def run(plan: Stage1Plan, state_dir: Path, wait: bool = False):
    state_dir.mkdir(parents=True, exist_ok=True)
    plan_hash = __import__("hashlib").sha256(json.dumps(asdict(plan), sort_keys=True).encode()).hexdigest()
    def status(stage, **details):
        write_text_atomic(state_dir / "status.json", json.dumps({"format": "hyd-stage1-status/1",
            "pid": os.getpid(), "plan_sha256": plan_hash, "stage": stage, "updated_unix": time.time(),
            "authority_enabled": False, **details}, indent=2))
    with WorkLease(state_dir / "pipeline.lock"):
        write_text_atomic(state_dir / "plan.json", json.dumps(asdict(plan), indent=2))
        try:
            corpus = Path(plan.corpus)
            while not ready(corpus):
                status("WAITING_FOR_SEALED_CORPUS", corpus=str(corpus),
                       compressed_bytes=sum(p.stat().st_size for p in corpus.glob("*.gz")))
                if not wait:
                    return {"stage": "WAITING_FOR_SEALED_CORPUS"}
                time.sleep(30)
            status("VERIFYING_CORPUS")
            verify_corpus(corpus)
            status("AUDITING_CORPUS")
            from hydra.hyd.corpus_quality import audit
            quality = audit(corpus, state_dir / "corpus-quality")
            if not quality["integrity_passed"]:
                raise ValueError("corpus quality audit failed; review corpus-quality/report.json")
            from hydra.hyd.corpus_quality import reviewed_warnings
            if quality["review_required"] and not reviewed_warnings(quality, plan.quality_review_path):
                status("CORPUS_REQUIRES_QUALITY_REVIEW", report=str(state_dir / "corpus-quality/report.json"))
                return {"stage": "CORPUS_REQUIRES_QUALITY_REVIEW"}
            from hydra.training import base_tokenizer as bt, base_pretrain as bp
            tokenizer = Path(plan.tokenizer)
            if not tokenizer.exists():
                status("TRAINING_TOKENIZER")
                temporary = tokenizer.with_name(tokenizer.name + ".partial-" + uuid.uuid4().hex[:8])
                bt.train(corpus, temporary, plan.vocab_size, plan.tokenizer_sample_characters)
                os.replace(temporary, tokenizer)
            tok_manifest = json.loads((tokenizer / "tokenizer-manifest.json").read_text(encoding="utf-8"))
            if (tok_manifest["corpus_manifest_sha256"] != canonical_sha256(corpus / "manifest.json")
                    or tok_manifest["tokenizer_model_sha256"] != file_sha256(tokenizer / "tokenizer.model")
                    or tok_manifest["vocab_size"] != plan.vocab_size):
                raise ValueError("stage-1 tokenizer belongs to a different corpus or vocabulary")
            tokens = Path(plan.tokens)
            if not tokens.exists():
                status("TOKENIZING_CORPUS")
                temporary = tokens.with_name(tokens.name + ".partial-" + uuid.uuid4().hex[:8])
                counts = bp.tokenize(corpus, tokenizer, temporary)
                write_text_atomic(temporary / "tokens-manifest.json", json.dumps({
                    "corpus_manifest_sha256": canonical_sha256(corpus / "manifest.json"),
                    "tokenizer_sha256": file_sha256(tokenizer / "tokenizer.model"),
                    "document_framing": "bos+document+eos", **counts}, indent=2))
                os.replace(temporary, tokens)
            token_manifest = bp.verify_tokens(tokens, corpus, tokenizer)
            decision_corpus = Path(plan.decision_corpus)
            if not decision_corpus.exists():
                status("BUILDING_VERIFIABLE_DECISIONS")
                from hydra.hyd.base_decisions import build
                temporary = decision_corpus.with_name(decision_corpus.name + ".partial-" + uuid.uuid4().hex[:8])
                build(corpus, Path(plan.synthetic_decisions), temporary)
                os.replace(temporary, decision_corpus)
            total = token_manifest["train"]["tokens"]
            if not plan.pretraining_authorized:
                status("PREPARED_AWAITING_PRETRAINING_ORDER", train_tokens=total,
                       validation_tokens=token_manifest["validation"]["tokens"],
                       estimate_hours_at_10500_tokens_s=total / 10500 / 3600,
                       pretraining_authorized=False)
                return {"stage": "PREPARED_AWAITING_PRETRAINING_ORDER", "train_tokens": total}
            status("WAITING_FOR_GPU", train_tokens=total, estimate_hours_at_10500_tokens_s=total / 10500 / 3600)
            import torch
            if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
                raise RuntimeError("stage-1 125M requires the reviewed CUDA BF16 environment")
            with WorkLease(state_dir.parent / "gpu-0.lock"):
                while torch.cuda.mem_get_info()[0] < plan.minimum_free_gpu_mib * 1024 * 1024:
                    status("WAITING_FOR_GPU", free_mib=torch.cuda.mem_get_info()[0] // (1024 * 1024))
                    if not wait:
                        return {"stage": "WAITING_FOR_GPU"}
                    time.sleep(30)
                base = Path(plan.base)
                if not (base / "build-manifest.json").exists():
                    status("PRETRAINING_125M", train_tokens=total, tokens_per_step=65536,
                           estimate_hours_at_10500_tokens_s=total / 10500 / 3600)
                    bp.train(tokens, tokenizer, base, bp.SHAPES["125m"], bp.PLANS["125m"], stage=1,
                             resume=base.exists(), device="cuda")
                    torch.cuda.empty_cache()
                base_manifest = json.loads((base / "build-manifest.json").read_text(encoding="utf-8"))
                if (base_manifest["data_manifest"] != token_manifest or base_manifest["stage"] != 1
                        or base_manifest["shape"] != asdict(bp.SHAPES["125m"])
                        or base_manifest["weights_sha256"] != file_sha256(base / "final/model.safetensors")):
                    raise ValueError("existing stage-1 base does not match this plan")
                model = Path(plan.decision_model)
                if not (model / "model.json").exists():
                    status("SUPERVISING_HYD_DECISIONS", base=str(base), corpus=plan.decision_corpus)
                    from hydra.hyd.train_neural import train
                    train(base / "final", Path(plan.decision_corpus), model, plan.decision_epochs,
                          plan.decision_max_tokens, plan.freeze_encoder, device="cuda", resume=model.exists())
            status("CANDIDATE_REQUIRES_EVALUATION", decision_model=plan.decision_model,
                   general_decision_parity="not established", production_config_changed=False)
            return {"stage": "CANDIDATE_REQUIRES_EVALUATION"}
        except Exception as exc:
            status("FAILED", error_type=type(exc).__name__, error=str(exc))
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--state-dir", type=Path, default=Path("runtime/hyd-stage1"))
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--authorize-pretraining", action="store_true",
                        help="Use only following an explicit human order to start pretraining")
    args = parser.parse_args()
    plan = Stage1Plan(**json.loads(args.plan.read_text(encoding="utf-8"))) if args.plan else Stage1Plan()
    plan.pretraining_authorized = args.authorize_pretraining
    print(json.dumps(run(plan, args.state_dir, args.wait), indent=2))
