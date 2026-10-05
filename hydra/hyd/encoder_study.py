# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYD-026 · Encoder study: stronger frozen encoders and supervised fine-tuning (SHADOW_ONLY, development).

Same leave-one-person-out folds as hybrid_lopo (families never cross partitions), plus an internal
development split carved from the training people of each fold:
  fit   -> train heads / fine-tune
  dev   -> every choice (encoder, C, learning rate, epoch); SHA256("dev:" + family) mod 5 == 0
  cal   -> temperature only (the hybrid_lopo calibration families)
  test  -> the held-out person, reported for every configuration but never used to choose one
These folds were already consulted by earlier experiments, so all results are development evidence,
not a blind promotion test. No weights are served and nothing gains authority.

Usage:
  python -m hydra.hyd.encoder_study frozen   --corpus corpus_v2.jsonl --out runs/study-1
  python -m hydra.hyd.encoder_study finetune --corpus corpus_v2.jsonl --out runs/study-1 --encoder e5-base
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import numpy as np

from hydra.hyd.hybrid_lopo import evaluate, fit_t, softmax_t, validate_folds

# name -> (hub id, pooling, text prefix, licence). Only MIT/Apache encoders.
ENCODERS = {
    "minilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "mean", "", "Apache-2.0"),
    "e5-base": ("intfloat/multilingual-e5-base", "mean", "query: ", "MIT"),
    "e5-large": ("intfloat/multilingual-e5-large", "mean", "query: ", "MIT"),
    "bge-m3": ("BAAI/bge-m3", "cls", "", "MIT"),
}
C_GRID = (0.25, 1.0, 4.0, 16.0)


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(corpus: Path):
    rows = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    folds = validate_folds(rows)
    families = np.array([r["family"] for r in rows])
    dev_family = np.array([int(hashlib.sha256(("dev:" + f).encode()).hexdigest()[:8], 16) % 5 == 0 for f in families])
    splits = {}
    for held, (fit, cal, test) in folds.items():
        dev = fit & dev_family
        fit = fit & ~dev_family
        for left, right in ((fit, dev), (dev, cal), (dev, test)):
            if set(families[left]) & set(families[right]):
                raise ValueError("family overlap between partitions")
        splits[held] = {"fit": fit, "dev": dev, "cal": cal, "test": test}
    return rows, splits


def nll(y, p, classes):
    idx = np.searchsorted(classes, y)
    return float(-np.log(p[np.arange(len(y)), idx] + 1e-12).mean())


def score(y, p, classes):
    out = evaluate(y, p, classes)
    out["nll"] = nll(y, p, classes)
    return out


def revision_of(hub_id: str) -> str:
    from huggingface_hub import HfApi
    return HfApi().model_info(hub_id).sha


def embed(name: str, texts: list[str], cache: Path) -> np.ndarray:
    if cache.exists():
        return np.load(cache, allow_pickle=False)
    import torch
    from sentence_transformers import SentenceTransformer
    hub, _, prefix, _ = ENCODERS[name]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(hub, device=device, revision=revision_of(hub))
    if device == "cuda":
        model.half()
    x = np.asarray(model.encode([prefix + t for t in texts], batch_size=64, normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    np.save(cache, x, allow_pickle=False)
    return x


def run_frozen(corpus: Path, out: Path, names: list[str]):
    from sklearn.linear_model import LogisticRegression
    from hydra.hyd.model import features

    rows, splits = load(corpus)
    out.mkdir(parents=True, exist_ok=True)
    texts = [r["text"] for r in rows]
    y = np.array([r["expected"] for r in rows])
    views = {"hash": np.stack([features(t + "\nInstructions: null", 512) for t in texts]).astype(np.float32)}
    revisions = {}
    for name in names:
        revisions[name] = revision_of(ENCODERS[name][0])
        views[name] = embed(name, texts, out / f"emb-{name}.npy")
        views[name + "+hash"] = np.hstack([views["hash"], views[name]])
    report = {"experiment": "HYD-026 encoder_study frozen", "status": "SHADOW_ONLY", "authority": False,
              "purpose": "development", "corpus_sha256": sha_file(corpus), "encoder_revisions": revisions,
              "selection": "mean dev macro-F1 over folds; the held-out person never chooses", "configs": {}}
    for view, x in views.items():
        for c in C_GRID:
            key = f"{view}|C={c}"
            entry = {"folds": {}}
            for held, s in splits.items():
                clf = LogisticRegression(C=c, max_iter=4000, random_state=42).fit(x[s["fit"]], y[s["fit"]])
                t = fit_t(clf, x[s["cal"]], y[s["cal"]])
                dev = score(y[s["dev"]], softmax_t(clf.decision_function(x[s["dev"]]), t), clf.classes_)
                test = score(y[s["test"]], softmax_t(clf.decision_function(x[s["test"]]), t), clf.classes_)
                entry["folds"][held] = {"dev": dev, "test": test, "temperature": t}
            entry["dev_macro_f1"] = float(np.mean([f["dev"]["macro_f1"] for f in entry["folds"].values()]))
            entry["dev_accuracy"] = float(np.mean([f["dev"]["accuracy"] for f in entry["folds"].values()]))
            entry["test_accuracy_pooled"] = pooled(entry["folds"], splits)
            report["configs"][key] = entry
            print(f"{key:24} dev F1 {entry['dev_macro_f1']:.3f} acc {entry['dev_accuracy']:.3f} | "
                  f"held-out acc {entry['test_accuracy_pooled']:.3f}", flush=True)
    best = max(report["configs"], key=lambda k: report["configs"][k]["dev_macro_f1"])
    report["selected_by_dev"] = best
    (out / "frozen-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def pooled(folds: dict, splits: dict) -> float:
    n = sum(int(splits[h]["test"].sum()) for h in folds)
    return float(sum(f["test"]["accuracy"] * int(splits[h]["test"].sum()) for h, f in folds.items()) / n)


class Classifier:
    """Encoder + linear head trained end to end (cross-entropy)."""

    def __init__(self, name: str, n_classes: int, device: str):
        import torch
        from transformers import AutoModel, AutoTokenizer
        hub, self.pooling, self.prefix, _ = ENCODERS[name]
        self.revision = revision_of(hub)
        self.tokenizer = AutoTokenizer.from_pretrained(hub, revision=self.revision)
        self.encoder = AutoModel.from_pretrained(hub, revision=self.revision).to(device)
        self.head = torch.nn.Linear(self.encoder.config.hidden_size, n_classes).to(device)
        self.device = device

    def parameters(self):
        return list(self.encoder.parameters()) + list(self.head.parameters())

    def train(self, mode=True):
        self.encoder.train(mode)
        self.head.train(mode)

    def logits(self, texts: list[str]):
        import torch
        batch = self.tokenizer([self.prefix + t for t in texts], padding=True, truncation=True, max_length=128,
                               return_tensors="pt").to(self.device)
        hidden = self.encoder(**batch).last_hidden_state
        if self.pooling == "cls":
            pooled_ = hidden[:, 0]
        else:
            mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled_ = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-6)
        return self.head(torch.nn.functional.normalize(pooled_, dim=-1) * 20.0)

    def predict_logits(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        import torch
        self.train(False)
        chunks = []
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16, enabled=self.device == "cuda"):
            for i in range(0, len(texts), batch_size):
                chunks.append(self.logits(texts[i:i + batch_size]).float().cpu().numpy())
        return np.concatenate(chunks)


def temperature(logits: np.ndarray, y: np.ndarray, classes: np.ndarray) -> float:
    idx = np.searchsorted(classes, y)
    best = (math.inf, 1.0)
    for t in np.linspace(0.3, 3, 28):
        p = softmax_t(logits, t)
        best = min(best, (-np.log(p[np.arange(len(y)), idx] + 1e-12).mean(), float(t)))
    return best[1]


def finetune_fold(name, texts, y, classes, s, lr, epochs, batch, seed, log, early_stop=False):
    import torch
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = Classifier(name, len(classes), device)
    index = {c: i for i, c in enumerate(classes)}
    fit_idx = np.flatnonzero(s["fit"])
    targets = torch.tensor([index[v] for v in y], device=device)
    optimizer = torch.optim.AdamW([{"params": model.encoder.parameters(), "lr": lr},
                                   {"params": model.head.parameters(), "lr": lr * 20}], weight_decay=0.01)
    steps = epochs * math.ceil(len(fit_idx) / batch)
    warmup = max(1, steps // 10)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda k: min(1.0, (k + 1) / warmup) * max(0.0, (steps - k) / max(1, steps - warmup)))
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    rng = np.random.default_rng(seed)
    dev_texts = [texts[i] for i in np.flatnonzero(s["dev"])]
    best = {"macro_f1": -1.0}
    history = []
    for epoch in range(1, epochs + 1):
        model.train(True)
        order = rng.permutation(fit_idx)
        started = time.time()
        total = 0.0
        for k in range(0, len(order), batch):
            ids = order[k:k + batch]
            with torch.autocast("cuda", dtype=torch.float16, enabled=device == "cuda"):
                loss = torch.nn.functional.cross_entropy(model.logits([texts[i] for i in ids]), targets[ids],
                                                         label_smoothing=0.05)
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            total += float(loss) * len(ids)
        dev_logits = model.predict_logits(dev_texts)
        dev = score(y[s["dev"]], softmax_t(dev_logits, 1.0), classes)
        history.append({"epoch": epoch, "train_loss": total / len(order), "dev_accuracy": dev["accuracy"],
                        "dev_macro_f1": dev["macro_f1"], "seconds": round(time.time() - started, 1)})
        log(f"    epoch {epoch} loss {total / len(order):.3f} dev acc {dev['accuracy']:.3f} F1 {dev['macro_f1']:.3f}")
        # Early stopping on the same-person dev split is optional: it measures in-distribution fit and was
        # found not to predict held-out-person accuracy, so the default keeps the fixed recipe's last epoch.
        if (dev["macro_f1"] > best["macro_f1"]) if early_stop else epoch == epochs:
            best = {"macro_f1": dev["macro_f1"], "epoch": epoch,
                    "state": {k: v.detach().to("cpu", copy=True) for k, v in model.encoder.state_dict().items()},
                    "head": {k: v.detach().to("cpu", copy=True) for k, v in model.head.state_dict().items()}}
    model.encoder.load_state_dict(best["state"])
    model.head.load_state_dict(best["head"])
    out = {}
    for part in ("dev", "cal", "test"):
        out[part] = model.predict_logits([texts[i] for i in np.flatnonzero(s[part])])
    revision = model.revision
    del model, optimizer, best["state"]
    if device == "cuda":
        torch.cuda.empty_cache()
    return out, history, revision


def run_finetune(corpus: Path, out: Path, name: str, lrs: list[float], epochs: int, batch: int, seed: int,
                 early_stop: bool = False):
    rows, splits = load(corpus)
    out.mkdir(parents=True, exist_ok=True)
    texts = [r["text"] for r in rows]
    y = np.array([r["expected"] for r in rows])
    classes = np.array(sorted(set(y)))
    log_path = out / f"finetune-{name}.log"

    def log(message):
        print(message, flush=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")

    report = {"experiment": "HYD-026 encoder_study finetune", "status": "SHADOW_ONLY", "authority": False,
              "purpose": "development", "encoder": ENCODERS[name][0], "licence": ENCODERS[name][3],
              "corpus_sha256": sha_file(corpus), "python": platform.python_version(), "seed": seed,
              "batch": batch, "max_epochs": epochs, "max_length": 128, "label_smoothing": 0.05,
              "selection": ("epoch by same-person dev macro-F1" if early_stop else
                            "fixed recipe declared before running (last epoch); dev reported only")
                           + "; temperature on cal; held-out person only reported",
              "configs": {}}
    for lr in lrs:
        key = f"{name}|lr={lr:g}"
        entry = {"folds": {}}
        for held, s in splits.items():
            log(f"{key} held-out {held}: fit {int(s['fit'].sum())} dev {int(s['dev'].sum())} "
                f"cal {int(s['cal'].sum())} test {int(s['test'].sum())}")
            logits, history, revision = finetune_fold(name, texts, y, classes, s, lr, epochs, batch, seed, log,
                                                      early_stop)
            t = temperature(logits["cal"], y[s["cal"]], classes)
            dev = score(y[s["dev"]], softmax_t(logits["dev"], t), classes)
            test = score(y[s["test"]], softmax_t(logits["test"], t), classes)
            entry["folds"][held] = {"dev": dev, "test": test, "temperature": t, "history": history,
                                    "best_epoch": max(history, key=lambda h: h["dev_macro_f1"])["epoch"]}
            report["encoder_revision"] = revision
            probs = softmax_t(logits["test"], t)
            idx = np.flatnonzero(s["test"])
            (out / f"ft-{name}-lr{lr:g}-{held}.predictions.jsonl").write_text("".join(
                json.dumps({"id": rows[j]["id"], "text_sha256": rows[j]["text_sha256"],
                            "probabilities": dict(zip(classes.tolist(), probs[i].round(6).tolist()))}) + "\n"
                for i, j in enumerate(idx)), encoding="utf-8")
            log(f"  -> dev acc {dev['accuracy']:.3f} F1 {dev['macro_f1']:.3f} | held-out acc {test['accuracy']:.3f} "
                f"F1 {test['macro_f1']:.3f} (T={t:.2f})")
        entry["dev_macro_f1"] = float(np.mean([f["dev"]["macro_f1"] for f in entry["folds"].values()]))
        entry["test_accuracy_pooled"] = pooled(entry["folds"], splits)
        report["configs"][key] = entry
        (out / f"finetune-{name}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    report["selected_by_dev"] = max(report["configs"], key=lambda k: report["configs"][k]["dev_macro_f1"])
    (out / f"finetune-{name}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["frozen", "finetune"])
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--encoders", default="minilm,e5-base,e5-large,bge-m3")
    ap.add_argument("--encoder", default="e5-base", choices=sorted(ENCODERS))
    ap.add_argument("--lrs", default="2e-5")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--early-stop", action="store_true", help="choose the epoch on the same-person dev split")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    if a.mode == "frozen":
        return run_frozen(a.corpus, a.out, [n.strip() for n in a.encoders.split(",") if n.strip()])
    return run_finetune(a.corpus, a.out, a.encoder, [float(v) for v in a.lrs.split(",")], a.epochs, a.batch, a.seed,
                        a.early_stop)


if __name__ == "__main__":
    main()
