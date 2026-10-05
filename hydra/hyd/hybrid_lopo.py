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
import argparse, hashlib, json, platform, re
from pathlib import Path
import numpy as np
from hydra.hyd.model import features

ENCODER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LABELS = {"chat", "research", "reasoning", "coding", "abstain", "privacy",
          "security", "vision", "tool_use", "high_risk_review"}


def validate_folds(rows):
    """Check all partitions before loading the encoder; never bypass leaks."""
    if not rows or any(not isinstance(r, dict) for r in rows):
        raise ValueError("nonempty corpus of records required")
    ids, texts, family_people = set(), set(), {}
    for row in rows:
        if (not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids
                or not isinstance(row.get("text"), str) or not row["text"].strip()
                or row.get("expected") not in LABELS):
            raise ValueError("invalid or duplicate corpus record")
        ids.add(row["id"])
        if hashlib.sha256(row["text"].encode()).hexdigest() != row.get("text_sha256"):
            raise ValueError("verbatim text SHA-256 mismatch")
        for key in ("person", "family"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("declared person and family required; no hash fallback")
        normalized = " ".join(row["text"].casefold().split())
        if normalized in texts:
            raise ValueError("duplicate normalized text; review groups before splitting")
        texts.add(normalized)
        previous = family_people.setdefault(row["family"], row["person"])
        if previous != row["person"]:
            raise ValueError("family leak across held-out people; review grouping")
    persons = np.array([r["person"] for r in rows])
    families = np.array([r["family"] for r in rows])
    labels = np.array([r["expected"] for r in rows])
    if len(set(persons)) < 3:
        raise ValueError("at least three declared people required for this LOPO protocol")
    calibration = np.array([int(hashlib.sha256(f.encode()).hexdigest()[:8], 16) % 5 == 0 for f in families])
    folds = {}
    for held in sorted(set(persons)):
        training = persons != held
        fit, cal, test = training & ~calibration, training & calibration, ~training
        if not fit.any() or not cal.any() or not test.any():
            raise ValueError("empty LOPO fit, calibration or test partition")
        for left, right in ((fit, cal), (fit, test), (cal, test)):
            if set(families[left]) & set(families[right]):
                raise ValueError("family overlap between partitions")
        if set(labels[fit]) != LABELS or set(labels[cal]) != LABELS:
            raise ValueError("fit and calibration must cover all ten classes")
        folds[str(held)] = (fit, cal, test)
    return folds


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
    ap.add_argument("--encoder-revision", required=True); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    if a.out.exists(): raise SystemExit("output directory already exists; choose a new run")
    if not re.fullmatch(r"[0-9a-f]{40}", a.encoder_revision):
        raise ValueError("encoder revision must be an exact 40-character commit SHA")
    rows = [json.loads(l) for l in a.corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    folds = validate_folds(rows)
    from sklearn.linear_model import LogisticRegression
    from sentence_transformers import SentenceTransformer
    import torch
    texts = [r["text"] for r in rows]
    y = np.array([r["expected"] for r in rows]); persons = np.array([r["person"] for r in rows])
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    enc = SentenceTransformer(ENCODER, device=dev, revision=a.encoder_revision)
    if dev == "cuda": enc.half()
    xs = np.asarray(enc.encode(texts, batch_size=128, normalize_embeddings=True, convert_to_numpy=True), dtype=np.float32)
    xh = np.stack([features(t + "\nInstructions: null", 512) for t in texts]).astype(np.float32)
    views = {"hash": xh, "semantic": xs, "hybrid": np.hstack([xh, xs])}
    report = {"experiment": "HYD-025 hybrid_lopo", "status": "SHADOW_ONLY", "authority": False, "encoder": ENCODER,
              "encoder_revision": a.encoder_revision, "device": dev, "python": platform.python_version(),
              "corpus_sha256": hashlib.sha256(a.corpus.read_bytes()).hexdigest(),
              "split": "LOPO; calibration = SHA256(declared family) mod 5 == 0",
              "protocol": "hyd-hybrid-lopo/2", "group_metadata_independently_verified": False,
              "folds": {}}
    for held in sorted(set(persons)):
        fit, cal, te = folds[str(held)]
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
