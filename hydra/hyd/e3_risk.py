"""E3 · Risk specialist (HYD-021, SHADOW_ONLY, never decides).

Same frozen multilingual encoder as E2 (paraphrase-multilingual-MiniLM-
L12-v2, ~118M) + a logistic head over 5 RISK GROUPS, not the 10 task
classes:

    risky  = abstain, high_risk_review, security, privacy
    other  = every remaining Hyd class collapsed

Goal: say how risky a question looks, so Hyd can later abstain-or-flag.
It NEVER decides: status stays SHADOW_ONLY, authority stays False. C and
temperature are chosen ONLY on the calibration split; the test split is
touched once for the report. Same frozen hash splits as
hydra.hyd.e2_semantic / hydra.hyd.app_corpus.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from collections import Counter
from pathlib import Path
import numpy as np

from hydra.hyd.e2_semantic import ENCODER, load, softmax

RISKY = ("abstain", "high_risk_review", "security", "privacy")


def to_group(label: str) -> str:
    """Collapse a Hyd class into its 5-group risk group."""
    return label if label in RISKY else "other"


def collapse(y):
    return [to_group(t) for t in y]


def metrics(y, probs, labels, min_conf):
    sel = probs.argmax(1); conf = probs.max(1)
    hits = np.array([labels[s] == t for s, t in zip(sel, y)])
    cm = {a: Counter() for a in labels}
    for t, s in zip(y, sel):
        cm[t][labels[s]] += 1
    per = {}
    for l in labels:
        tp = cm[l][l]; fp = sum(cm[o][l] for o in labels) - tp; fn = sum(cm[l].values()) - tp
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
        per[l] = {"precision": round(pr, 3), "recall": round(rc, 3),
                  "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0, "support": sum(cm[l].values())}
    n = len(y); ece = 0.0
    for i in range(10):
        m = (conf > i / 10) & (conf <= (i + 1) / 10)
        if m.any():
            ece += m.sum() / n * abs(hits[m].mean() - conf[m].mean())
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
    ap.add_argument("--dataset", type=Path, required=True, help="hyd-app-corpus-v1 (same frozen splits as E2)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression

    Xtr, ytr = load(a.dataset / "train.jsonl"); Xca, yca = load(a.dataset / "calibration.jsonl"); Xte, yte = load(a.dataset / "test.jsonl")
    gtr, gca, gte = collapse(ytr), collapse(yca), collapse(yte)
    enc = SentenceTransformer(ENCODER, device="cpu")
    E = lambda X: enc.encode(X, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    etr, eca, ete = E(Xtr), E(Xca), E(Xte)
    labels = sorted(set(gtr))
    best = None
    for C in (0.5, 1, 2, 4, 8, 16, 32):
        clf = LogisticRegression(C=C, max_iter=3000).fit(etr, gtr)
        acc = (clf.predict(eca) == np.array(gca)).mean()
        if best is None or acc > best[0]:
            best = (acc, C, clf)
    _, C, clf = best
    assert list(clf.classes_) == labels
    gi = np.array([labels.index(t) for t in gca]); lca = clf.decision_function(eca)
    T = min(np.arange(0.3, 3.01, 0.05), key=lambda t: -np.log(softmax(lca / t)[np.arange(len(gi)), gi] + 1e-12).mean())
    pte = softmax(clf.decision_function(ete) / T)
    rep = {"format": "hyd-e3-report/1", "model": "e3-risk-v1", "encoder": ENCODER,
           "groups": labels, "risky": list(RISKY),
           "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "head": {"type": "logistic", "C": C}, "temperature": round(float(T), 3),
           "dataset_sha256": hashlib.sha256((a.dataset / "test.jsonl").read_bytes()).hexdigest(),
           "n_train": len(gtr), "n_calibration": len(gca), **metrics(gte, pte, labels, 0.85),
           "status": "SHADOW_ONLY", "authority": False,
           "note": "Risk observer only: never decides, never blocks, never touches the question."}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    np.savez(a.out / "head.npz", coef=clf.coef_, intercept=clf.intercept_, labels=np.array(labels), T=T)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1", "ece", "temperature")}))


if __name__ == "__main__":
    main()
