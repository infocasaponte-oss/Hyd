# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded, family/class-balanced encoder tuning without changing legacy inference hashes."""
import copy
import hashlib
from collections import Counter
from pathlib import Path

import numpy as np

from hydra.training.decision_active_learning import text_label
from hydra.training.decision_candidates import group, validate
from hydra.training.decision_finetune import encoder_identity
from hydra.training.evidence_io import write_json


def balanced_weights(rows):
    counts = Counter(group(row) for row in rows)
    mass = Counter()
    for row in rows:
        mass[text_label(row)[1]] += 1 / counts[group(row)]
    weights = np.array([1 / counts[group(row)] / mass[text_label(row)[1]] for row in rows], dtype=np.float32)
    return weights * len(rows) / weights.sum()


def tune(parts, spec, out, labels, *, epochs=3, seed=42):
    validate(parts)
    if spec['kind'] != 'minilm' or not 1 <= epochs <= 5:
        raise ValueError('cached MiniLM and bounded epochs 1..5 required')
    if set(text_label(row)[1] for row in parts['fit']) != set(labels):
        raise ValueError('all labels must be present in admitted fit')
    import torch
    from sentence_transformers import SentenceTransformer
    torch.manual_seed(seed)
    device = spec.get('device', 'cpu')
    encoder = SentenceTransformer(spec['model'], revision=spec['revision'], device=device, local_files_only=True)
    encoder.max_seq_length = 128
    for parameter in encoder.parameters():
        parameter.requires_grad_(False)
    for layer in encoder[0].auto_model.encoder.layer[-2:]:
        for parameter in layer.parameters():
            parameter.requires_grad_(True)
    head = torch.nn.Linear(spec['dims'], len(labels)).to(device)
    trainable = [p for p in encoder.parameters() if p.requires_grad] + list(head.parameters())
    optimizer = torch.optim.AdamW(trainable, lr=2e-5)
    fit = parts['fit']
    weights = torch.tensor(balanced_weights(fit), device=device)
    curves, best, best_state = [], float('inf'), None
    for epoch in range(epochs):
        encoder.train()
        order = torch.randperm(len(fit)).tolist()
        losses = []
        batches = [order[start:start + 8] for start in range(0, len(fit), 8)]
        for block_start in range(0, len(batches), 4):
            block = batches[block_start:block_start + 4]
            block_size = sum(len(indices) for indices in block)
            optimizer.zero_grad()
            for indices in block:
                batch = [fit[i] for i in indices]
                tokens = {k: v.to(device) if torch.is_tensor(v) else v
                          for k, v in encoder.tokenize([text_label(r)[0] for r in batch]).items()}
                embedding = encoder(tokens)['sentence_embedding']
                targets = torch.tensor([labels.index(text_label(r)[1]) for r in batch], device=device)
                loss = (torch.nn.functional.cross_entropy(head(embedding), targets, reduction='none') * weights[indices]).sum()
                (loss / block_size).backward()
                losses.append(float(loss.detach()) / len(indices))
            torch.nn.utils.clip_grad_norm_(trainable, 1)
            optimizer.step()
        encoder.eval()
        with torch.no_grad():
            vectors = encoder.encode([text_label(r)[0] for r in parts['dev']], convert_to_tensor=True, batch_size=16)
            targets = torch.tensor([labels.index(text_label(r)[1]) for r in parts['dev']], device=device)
            logits = head(vectors)
            dev_loss = float(torch.nn.functional.cross_entropy(logits, targets))
            dev_accuracy = float((logits.argmax(1) == targets).float().mean())
        curves.append({'epoch': epoch + 1, 'fit_weighted_loss': sum(losses) / len(losses),
                       'dev_loss': dev_loss, 'dev_accuracy': dev_accuracy})
        print({'encoder_epoch': epoch + 1, 'dev_accuracy': dev_accuracy}, flush=True)
        if dev_loss < best:
            best = dev_loss
            best_state = copy.deepcopy({k: v.detach().cpu() for k, v in encoder.state_dict().items()})
    encoder.load_state_dict(best_state)
    encoder.eval()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    encoder.save(str(out))
    identity = encoder_identity(out)
    write_json(out.parent / (out.name + '-tuning.json'), {'curves': curves, 'selected_by': 'dev_loss_only',
        'epochs': epochs, 'seed': seed, 'learning_rate': 2e-5, 'trainable_layers': 'last_two',
        'weighting': 'equal_class_then_scenario', 'encoder_sha256': identity,
        'training_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'test_consulted': False, 'authority': False})
    return {'kind': 'minilm-finetuned', 'model': str(out.resolve()), 'dims': spec['dims'],
            'weights_sha256': identity, 'device': device, 'memory': spec.get('memory', False)}
