# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Optional incremental encoder tuning. Fit gradients, dev stopping, never test labels."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from hydra.training.decision_active_learning import text_label
from hydra.training.evidence_io import write_json


def encoder_identity(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).replace("\\", "/").encode())
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def tune(parts, spec, out, labels, *, epochs=1, seed=42, learning_rate=2e-5):
    if spec["kind"] != "minilm" or not 1 <= epochs <= 5 or learning_rate not in (1e-5, 2e-5, 5e-5):
        raise ValueError("bounded MiniLM tuning: epochs 1..5, fixed learning-rate grid")
    import torch
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(seed)
    device = spec.get("device", "cpu")
    encoder = SentenceTransformer(spec["model"], revision=spec["revision"], device=device, local_files_only=True)
    encoder.max_seq_length = 128
    for parameter in encoder.parameters():
        parameter.requires_grad_(False)
    layers = encoder[0].auto_model.encoder.layer
    for layer in layers[-2:]:
        for parameter in layer.parameters():
            parameter.requires_grad_(True)
    head = torch.nn.Linear(spec["dims"], len(labels)).to(device)
    trainable = [p for p in encoder.parameters() if p.requires_grad] + list(head.parameters())
    optimizer = torch.optim.AdamW(trainable, lr=learning_rate)
    fit = parts["fit"]
    curves, best, best_state = [], float("inf"), None
    for epoch in range(epochs):
        encoder.train()
        order = torch.randperm(len(fit)).tolist()
        losses = []
        optimizer.zero_grad()
        for batch_index, start in enumerate(range(0, len(fit), 8)):
            batch = [fit[i] for i in order[start:start + 8]]
            # SentenceTransformers 6 includes non-tensor text metadata in this mapping.
            tokens = {k: v.to(device) if torch.is_tensor(v) else v
                      for k, v in encoder.tokenize([text_label(r)[0] for r in batch]).items()}
            embedding = encoder(tokens)["sentence_embedding"]
            target = torch.tensor([labels.index(text_label(r)[1]) for r in batch], device=device)
            loss = torch.nn.functional.cross_entropy(head(embedding), target)
            (loss / 4).backward()
            losses.append(float(loss.detach()))
            if (batch_index + 1) % 4 == 0 or start + 8 >= len(fit):
                torch.nn.utils.clip_grad_norm_(trainable, 1)
                optimizer.step()
                optimizer.zero_grad()
        encoder.eval()
        with torch.no_grad():
            vectors = encoder.encode([text_label(r)[0] for r in parts["dev"]], convert_to_tensor=True, batch_size=16)
            expected = torch.tensor([labels.index(text_label(r)[1]) for r in parts["dev"]], device=device)
            logits = head(vectors)
            dev_loss = float(torch.nn.functional.cross_entropy(logits, expected))
            dev_accuracy = float((logits.argmax(1) == expected).float().mean())
        curves.append({"epoch": epoch + 1, "fit_loss": sum(losses) / len(losses),
                       "dev_loss": dev_loss, "dev_accuracy": dev_accuracy})
        if dev_loss < best:
            best = dev_loss
            best_state = copy.deepcopy({k: v.detach().cpu() for k, v in encoder.state_dict().items()})
    encoder.load_state_dict(best_state)
    encoder.eval()
    out.mkdir(parents=True, exist_ok=False)
    encoder.save(str(out))
    identity = encoder_identity(out)
    write_json(out.parent / "encoder-tuning.json", {"curves": curves, "selected_by": "dev_loss_only",
        "epochs": epochs, "seed": seed, "learning_rate": learning_rate, "trainable_layers": "last_two",
        "encoder_sha256": identity, "test_consulted": False, "authority": False})
    return {"kind": "minilm-finetuned", "model": str(out.resolve()), "dims": spec["dims"],
            "weights_sha256": identity, "device": device, "memory": spec.get("memory", False)}
