# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Supervise Hyd's contextual scorer on admitted local typed records."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.hyd.model import render
from hydra.hyd.neural import ContextRanker, FORMAT
from hydra.hyd.train_typed import read_partition, options
from hydra.router.decision_contract import CRITERIA
from hydra.training.base_corpus import file_sha256
from hydra.training.calibrator import fit_temperature
from hydra.training.decision_metrics import metrics


def train(base: Path, corpus: Path, out: Path, epochs: int = 2, max_tokens: int = 512,
          freeze_encoder: bool = True, device: str | None = None, resume: bool = False):
    import torch
    from safetensors.torch import save_file
    from transformers import LlamaModel, AutoTokenizer

    if out.exists() and not resume:
        raise FileExistsError("use a new contextual Hyd candidate directory")
    if not 1 <= epochs <= 100 or not 32 <= max_tokens <= 65536:
        raise ValueError("invalid contextual training limits")
    manifest_path = base.parent / "build-manifest.json"
    lineage = json.loads(manifest_path.read_text(encoding="utf-8"))
    if lineage.get("kind") != "hydra-base" or lineage.get("weights_sha256") != file_sha256(base / "model.safetensors"):
        raise ValueError("contextual training requires a verified HYDRA Base checkpoint")
    if lineage.get("tokenizer_sha256") != file_sha256(base / "tokenizer.model"):
        raise ValueError("HYDRA Base tokenizer lineage mismatch")
    corpus_manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in corpus_manifest["files"].items():
        if Path(name).name != name or file_sha256(corpus / name) != entry["sha256"]:
            raise ValueError("typed training corpus checksum mismatch")
    training = read_partition(corpus / "train.jsonl", "train", allow_licensed=True)
    calibration = read_partition(corpus / "calibration.jsonl", "calibration", allow_licensed=True)
    for row in training + calibration:
        if row["rights"]["license"] != "proprietary-hydra-authored" and (
                row["rights"].get("source_manifest_sha256") != corpus_manifest.get("parent_base_corpus_sha256")):
            raise ValueError("licensed decision row is not bound to the corpus lineage")
    if {r["family"] for r in training} & {r["family"] for r in calibration}:
        raise ValueError("contextual train/calibration family overlap")
    if {render(r["state"]) for r in training} & {render(r["state"]) for r in calibration}:
        raise ValueError("contextual train/calibration state overlap")
    torch.manual_seed(42)
    target_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
    backbone = LlamaModel.from_pretrained(base, local_files_only=True, use_safetensors=True).to(target_device)
    if max_tokens > backbone.config.max_position_embeddings or tokenizer.pad_token_id is None:
        raise ValueError("contextual training exceeds backbone or tokenizer limits")
    width = backbone.config.hidden_size
    head = torch.nn.Sequential(torch.nn.Linear(width, width // 2), torch.nn.GELU(), torch.nn.Linear(width // 2, 1)).to(target_device)
    ranker = ContextRanker(backbone, tokenizer, head, target_device, max_tokens)
    domains, encoded = {}, []
    for row in training + calibration:
        question = row["question"]
        candidates = options(question)
        if len(candidates) > 16:
            raise ValueError("contextual training is bounded to 16 candidates per record")
        keys = sorted(candidates)
        ids = [ranker.encode(row["state"], question.get("instructions"), key, candidates[key]) for key in keys]
        if row["split"] == "train":
            encoded.append((ids, [row["target"][key] for key in keys]))
            domain = {"type": question["type"], "criteria": question.get("criteria"),
                      "instructions": question.get("instructions")}
            domains[render(domain)] = domain
    out.mkdir(parents=True, exist_ok=resume)
    backbone.requires_grad_(not freeze_encoder)
    if not freeze_encoder:
        backbone.gradient_checkpointing_enable()
        backbone.config.use_cache = False
    optimizer = torch.optim.AdamW([p for module in (backbone, head) for p in module.parameters() if p.requires_grad],
                                 lr=1e-3 if freeze_encoder else 3e-5, weight_decay=.01)
    identity = {"base_sha256": file_sha256(base / "model.safetensors"),
                "corpus_sha256": file_sha256(corpus / "manifest.json"), "epochs": epochs,
                "max_tokens": max_tokens, "freeze_encoder": freeze_encoder,
                "torch": str(torch.__version__), "device": target_device.type,
                "trainer_sha256": file_sha256(Path(__file__))}
    generator = torch.Generator().manual_seed(42)
    history, first_epoch, prior_runtime = [], 0, 0.0
    if resume:
        from hydra.training.base_pretrain import load_resume
        payload = load_resume(out, identity, target_device)
        head.load_state_dict(payload["head"])
        if not freeze_encoder:
            backbone.load_state_dict(payload["encoder"])
        optimizer.load_state_dict(payload["optimizer"])
        generator.set_state(payload["shuffle_rng"].cpu())
        torch.set_rng_state(payload["torch_rng"].cpu())
        if target_device.type == "cuda":
            torch.cuda.set_rng_state_all([state.cpu() for state in payload["cuda_rng"]])
        first_epoch, history, prior_runtime = payload["step"], payload["history"], payload["runtime_s"]
    cached = []
    started = time.time()
    log_path = out / "training.jsonl"
    if freeze_encoder:
        with torch.no_grad():
            for index, (ids, target) in enumerate(encoded):
                cached.append((ranker.hidden(ids).detach(), torch.tensor(target, device=target_device)))
                if (index + 1) % 100 == 0:
                    with log_path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"phase": "encode", "records": index + 1, "elapsed_s": time.time() - started}) + "\n")
    for epoch in range(first_epoch, epochs):
        head.train()
        backbone.eval() if freeze_encoder else backbone.train()
        total_loss = 0.0
        for index in torch.randperm(len(encoded), generator=generator).tolist():
            if freeze_encoder:
                hidden, target = cached[index]
            else:
                ids, expected = encoded[index]
                hidden, target = ranker.hidden(ids), torch.tensor(expected, device=target_device)
            logits = head(hidden).reshape(-1)
            loss = -(target * torch.log_softmax(logits, dim=0)).sum()
            if not torch.isfinite(loss):
                raise ValueError("nonfinite contextual training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for module in (backbone, head) for p in module.parameters() if p.requires_grad], 1)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            total_loss += float(loss.detach().cpu())
        history.append({"epoch": epoch + 1, "loss": total_loss / len(encoded), "runtime_s": prior_runtime + time.time() - started})
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(history[-1]) + "\n")
        # Recoverable epoch snapshots; never erase a previous completed epoch.
        snapshot = out / f"epoch-{epoch + 1}"
        snapshot.mkdir(exist_ok=True)
        save_file({k: v.detach().contiguous().cpu() for k, v in head.state_dict().items()}, snapshot / "head.safetensors")
        if not freeze_encoder:
            backbone.save_pretrained(snapshot / "encoder", safe_serialization=True)
        from hydra.training.base_pretrain import save_resume
        save_resume(out / "resume.pt", {"identity": identity, "step": epoch + 1,
                    "head": head.state_dict(), "encoder": backbone.state_dict() if not freeze_encoder else {},
                    "optimizer": optimizer.state_dict(), "history": history, "shuffle_rng": generator.get_state(),
                    "torch_rng": torch.get_rng_state(),
                    "cuda_rng": torch.cuda.get_rng_state_all() if target_device.type == "cuda" else [],
                    "runtime_s": prior_runtime + time.time() - started})
    backbone.eval()
    head.eval()
    scored = []
    for row in calibration:
        p = ranker.probabilities(row["state"], row["question"].get("instructions"), options(row["question"]))
        scored.append({"expected": max(row["target"], key=row["target"].get), "probabilities": p,
                       "selected": max(p, key=p.get)})
    hard_rows = [r for r, source in zip(scored, calibration) if max(source["target"].values()) == 1]
    ranker.temperature = fit_temperature(hard_rows) if hard_rows else 1.0
    save_file({k: v.detach().contiguous().cpu() for k, v in head.state_dict().items()}, out / "head.safetensors")
    saved_base = base.resolve()
    if not freeze_encoder:
        saved_base = (out / "encoder").resolve()
        backbone.save_pretrained(saved_base, safe_serialization=True)
        for name in ("tokenizer.model", "tokenizer_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer.vocab"):
            if (base / name).exists():
                shutil.copy2(base / name, saved_base / name)
    model = {"format": FORMAT, "origin": "HYDRA Base", "base_directory": os.path.relpath(saved_base, out.resolve()),
             "base_weights_sha256": file_sha256(saved_base / "model.safetensors"),
             "tokenizer_sha256": file_sha256(saved_base / "tokenizer.model"),
             "head_sha256": file_sha256(out / "head.safetensors"), "max_tokens": max_tokens,
             "temperature": ranker.temperature, "training": {"question_domains": list(domains.values()),
                 "domain": "typed_registered_questions", "examples": len(training), "epochs": epochs,
                 "frozen_encoder": freeze_encoder, "general_decision_quality": "unvalidated",
                 "source_manifest_sha256": file_sha256(corpus / "manifest.json"),
                 "base_manifest_sha256": file_sha256(manifest_path)}}
    write_text_atomic(out / "model.json", json.dumps(model, ensure_ascii=False, indent=2))
    from hydra.hyd.controller import implementation_digest
    calibration_manifest = {"format": "hyd-calibration/1", "model_sha256": file_sha256(out / "model.json"),
        "implementation_sha256": implementation_digest(), "temperature": ranker.temperature,
        "dataset_sha256": file_sha256(corpus / "calibration.jsonl"), "criteria": CRITERIA,
        "min_confidence": .95, "min_margin": .1, "status": "SHADOW_ONLY", "independent_test": False}
    write_text_atomic(out / "calibration.json", json.dumps(calibration_manifest, indent=2))
    report = {"format": "hyd-contextual-training/1", "model_revision": calibration_manifest["model_sha256"],
              "status": "REQUIRES_INDEPENDENT_EVALUATION", "history": history,
              "uncalibrated_diagnostics": metrics(scored), "runtime_s": prior_runtime + time.time() - started,
              "parameters": sum(p.numel() for p in backbone.parameters()) + sum(p.numel() for p in head.parameters()),
              "environment": {"torch": torch.__version__, "device": str(target_device)}, "authority_enabled": False}
    write_text_atomic(out / "training.json", json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path("data/hyd-typed-corpus-v2"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--unfreeze-encoder", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.base, args.corpus, args.out, args.epochs, args.max_tokens,
                           not args.unfreeze_encoder, resume=args.resume), indent=2))
