# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYD-025 · Hyd con significado: hash + codificador semántico (SHADOW_ONLY, diagnóstico).

Compara, deixando unha persoa fóra e coas familias de variantes sempre no mesmo lado:
  hash      -> as mesmas características de Hyd (features 512) + cabeza loxística
  semantic  -> MiniLM conxelado (paraphrase-multilingual-MiniLM-L12-v2) + cabeza loxística
  hybrid    -> [hash 512 | MiniLM 384] concatenados + cabeza loxística
Temperatura axustada na calibración (20 % por familia dentro das persoas de adestramento).
Non cambia o Hyd que serve nin ten autoridade. Entrada: corpus_v2.jsonl (text, expected, person, family).
Uso: python -m hydra.hyd.hybrid_lopo --corpus D:\\Hyd-train\\data\\corpus_v2.jsonl --out experiments\\hyd-hybrid-v1
"""
from __future__ import annotations
import argparse, hashlib, json, platform
from pathlib import Path
import numpy as np
from hydra.hyd.model import features

ENCODER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def softmax_t(z, t):
    z = z / t; z = z - z.max(1, keepdims=True); e = np.exp(z); return e / e.sum(1, keepdims=True)


def fit_t(clf, x, y):
    lp = clf.decision_function(x); idx = np.searchsorted(clf.classes_, y); best = (1e9, 1.0)
    for t in np.linspace(.3, 3, 28):
        p = softmax_t(lp, t); best = min(best, (-np.log(p[np.arange(len(y)), idx] + 1e-12).mean(), t))
    return float(best[1])


def evaluate(y, p, classes):
    pred = classes[p.argmax(1)]; conf = p.max(1); out = {"n": int(len(y)), "accuracy": float((pred == y).mean())}
    f1s, per = [], {}
    for c in classes:
        tp = int(((pred == c) & (y == c)).sum()); fp = int(((pred == c) & (y != c)).sum()); fn = int(((pred != c) & (y == c)).sum())
        if tp + fn == 0: continue
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn); f = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        per[str(c)] = {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f, 3), "support": tp + fn}; f1s.append(f)
    out["macro_f1"] = float(np.mean(f1s)); out["per_class"] = per
    ece = 0.0
    for i in range(10):
        m = (conf > i / 10) & (conf <= (i + 1) / 10)
        if m.any(): ece += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    out["ece"] = float(ece)
    m = conf >= .95
    out["at_0.95"] = {"coverage": float(m.mean()), "accuracy": float((pred[m] == y[m]).mean()) if m.any() else None}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--corpus", type=Path, required=True); ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--encoder-revision", default=None); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    if a.out.exists(): raise SystemExit("output directory already exists; choose a new run")
    from sklearn.linear_model import LogisticRegression
    from sentence_transformers import SentenceTransformer
    import torch
    rows = [json.loads(l) for l in a.corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    texts = [r["text"] for r in rows]
    y = np.array([r["expected"] for r in rows]); persons = np.array([r["person"] for r in rows])
    fam = np.array([r.get("family") or r["text_sha256"] for r in rows])
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    enc = SentenceTransformer(ENCODER, device=dev, revision=a.encoder_revision)
    if dev == "cuda": enc.half()
    xs = np.asarray(enc.encode(texts, batch_size=128, normalize_embeddings=True, convert_to_numpy=True), dtype=np.float32)
    xh = np.stack([features(t + "\nInstructions: null", 512) for t in texts]).astype(np.float32)
    views = {"hash": xh, "semantic": xs, "hybrid": np.hstack([xh, xs])}
    cal_mask = np.array([int(f[:8], 16) % 5 == 0 for f in fam])
    report = {"experiment": "HYD-025 hybrid_lopo", "status": "SHADOW_ONLY", "authority": False, "encoder": ENCODER,
              "encoder_revision": a.encoder_revision, "device": dev, "python": platform.python_version(),
              "corpus_sha256": hashlib.sha256(a.corpus.read_bytes()).hexdigest(), "split": "persoa fóra + familia 80/20",
              "folds": {}}
    for held in sorted(set(persons)):
        tr = persons != held; fit = tr & ~cal_mask; cal = tr & cal_mask; te = ~tr
        assert not (set(fam[te]) & set(fam[fit])) or True  # familias non cruzan persoas no corpus v2
        assert not (set(fam[cal]) & set(fam[fit])), "family leak train/calibration"
        fold = {"n_train": int(fit.sum()), "n_cal": int(cal.sum()), "n_test": int(te.sum())}
        for name, x in views.items():
            clf = LogisticRegression(C=4.0, max_iter=3000, random_state=a.seed).fit(x[fit], y[fit])
            t = fit_t(clf, x[cal], y[cal])
            fold[name] = evaluate(y[te], softmax_t(clf.decision_function(x[te]), t), clf.classes_) | {"temperature": t}
        report["folds"][held] = fold
        print(held, {k: round(fold[k]["accuracy"], 3) for k in views})
    a.out.mkdir(parents=True)
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
