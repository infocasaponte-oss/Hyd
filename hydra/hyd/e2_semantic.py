"""E2 · Semantic specialist (SHADOW_ONLY, never decides).

Frozen multilingual sentence encoder (~118M params, runs on CPU or a
3060 Ti in fp16) + logistic head. C and temperature are chosen ONLY on
the calibration split; the test split is touched once for the report.
Same frozen splits and same metrics as hydra.hyd.app_corpus.report.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from collections import Counter
from pathlib import Path
import numpy as np

ENCODER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def load(p: Path):
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r["input"]["query"] for r in rows], [r["output"]["task_type"] for r in rows]


def softmax(z):
    z = z - z.max(1, keepdims=True); e = np.exp(z); return e / e.sum(1, keepdims=True)


def metrics(y, probs, labels, min_conf):
    sel = probs.argmax(1); conf = probs.max(1)
    hits = np.array([labels[s] == t for s, t in zip(sel, y)])
    cm = {a: Counter() for a in labels}
    for t, s in zip(y, sel): cm[t][labels[s]] += 1
    per = {}
    for l in labels:
        tp = cm[l][l]; fp = sum(cm[o][l] for o in labels) - tp; fn = sum(cm[l].values()) - tp
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
        per[l] = {"precision": round(pr, 3), "recall": round(rc, 3),
                  "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0, "support": sum(cm[l].values())}
    n = len(y); ece = 0.0
    for i in range(10):
        m = (conf > i / 10) & (conf <= (i + 1) / 10)
        if m.any(): ece += m.sum() / n * abs(hits[m].mean() - conf[m].mean())
    cov = {}
    for th in (0.0, 0.4, 0.55, 0.7, 0.85, min_conf):
        m = conf >= th
        cov[str(round(th, 3))] = {"coverage": round(float(m.mean()), 3),
                                  "accuracy": round(float(hits[m].mean()), 3) if m.any() else None}
    return {"n": n, "accuracy": round(float(hits.mean()), 3),
            "macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3),
            "ece": round(float(ece), 3), "per_class": per, "min_confidence": cov,
            "confusion": {a: dict(cm[a]) for a in labels}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    enc = SentenceTransformer(ENCODER, device="cpu")
    Xtr, ytr = load(a.dataset / "train.jsonl"); Xca, yca = load(a.dataset / "calibration.jsonl"); Xte, yte = load(a.dataset / "test.jsonl")
    E = lambda X: enc.encode(X, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    etr, eca, ete = E(Xtr), E(Xca), E(Xte)
    labels = sorted(set(ytr))
    best = None
    for C in (0.5, 1, 2, 4, 8, 16, 32):
        clf = LogisticRegression(C=C, max_iter=3000).fit(etr, ytr)
        acc = (clf.predict(eca) == np.array(yca)).mean()
        if best is None or acc > best[0]: best = (acc, C, clf)
    _, C, clf = best
    assert list(clf.classes_) == labels
    yi = np.array([labels.index(t) for t in yca]); lca = clf.decision_function(eca)
    T = min(np.arange(0.3, 3.01, 0.05), key=lambda t: -np.log(softmax(lca / t)[np.arange(len(yi)), yi] + 1e-12).mean())
    pca = softmax(lca / T); conf = pca.max(1); hit = pca.argmax(1) == yi
    # smallest threshold with >=95 % accuracy on calibration
    mc = next((float(t) for t in np.arange(0.4, 0.99, 0.01) if (conf >= t).any() and hit[conf >= t].mean() >= 0.95), 0.95)
    pte = softmax(clf.decision_function(ete) / T)
    rep = {"format": "hyd-e2-report/1", "model": "e2-semantic-v1", "encoder": ENCODER,
           "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "head": {"type": "logistic", "C": C}, "temperature": round(float(T), 3), "min_confidence_cal": round(mc, 3),
           "dataset_sha256": hashlib.sha256((a.dataset / "test.jsonl").read_bytes()).hexdigest(),
           "n_train": len(ytr), "n_calibration": len(yca), **metrics(yte, pte, labels, mc),
           "status": "SHADOW_ONLY", "authority": False,
           "note": "Real corpus only; frozen hash splits; observes, never decides."}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    np.savez(a.out / "head.npz", coef=clf.coef_, intercept=clf.intercept_, labels=np.array(labels), T=T)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1", "ece", "temperature", "min_confidence_cal")}))


if __name__ == "__main__":
    main()
