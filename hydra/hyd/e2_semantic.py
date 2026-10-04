"""E2 · Semantic specialist (SHADOW_ONLY, never decides).

Frozen multilingual sentence encoder (~118M params, runs on CPU or a
3060 Ti in fp16) + logistic head. C is chosen on development; temperature and thresholds use separate groups in
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
    ap.add_argument("--encoder-revision", required=True)
    ap.add_argument("--target", type=float, default=0.95)
    ap.add_argument("--min-coverage", type=float, default=0.1)
    a = ap.parse_args()
    if not 0 < a.target < 1 or not 0 < a.min_coverage <= 1:
        raise ValueError("invalid target or coverage")
    if a.out.exists():
        raise ValueError("output directory already exists; choose a new run")
    from hyd_calibrator.e2_admission import admit_dataset
    admitted, partition_hashes = admit_dataset(a.dataset, a.encoder_revision, require_development=True)
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    enc = SentenceTransformer(ENCODER, revision=a.encoder_revision, device="cpu")
    def partition(split):
        rows = admitted[split]
        return [r["input"]["query"] for r in rows], [r["output"]["task_type"] for r in rows]
    Xtr, ytr = partition("train"); Xca, yca = partition("calibration"); Xte, yte = partition("test")
    E = lambda X: enc.encode(X, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    Xdev, ydev = partition("development")
    etr, edev, eca = E(Xtr), E(Xdev), E(Xca)
    labels = sorted(set(ytr))
    best = None
    for C in (0.5, 1, 2, 4, 8, 16, 32):
        clf = LogisticRegression(C=C, max_iter=3000).fit(etr, ytr)
        acc = (clf.predict(edev) == np.array(ydev)).mean()
        if best is None or acc > best[0]: best = (acc, C, clf)
    _, C, clf = best
    assert list(clf.classes_) == labels
    yi = np.array([labels.index(t) for t in yca]); lca = clf.decision_function(eca)
    from hyd_calibrator.e2_calibration import calibrate_logits
    from hyd_calibrator.evaluation import selective
    calibration = calibrate_logits(lca, yi, admitted["calibration"], a.target, a.min_coverage)
    T = calibration["temperature"]
    mc = calibration["min_confidence"]
    # Test embeddings and predictions are produced after all selections are fixed.
    pte = softmax(clf.decision_function(E(Xte)) / T)
    ordered = np.sort(pte, axis=1)
    test_hits = [labels[index] == truth for index, truth in zip(pte.argmax(1), yte)]
    test_selective = selective(ordered[:, -1].tolist(), (ordered[:, -1] - ordered[:, -2]).tolist(),
                              test_hits, mc, calibration["min_margin"], calibration["abstain_all"])
    rep = {"format": "hyd-e2-report/2", "encoder_revision": a.encoder_revision,
           "partition_sha256": partition_hashes, "independence_verified": False, "model": "e2-semantic-v1", "encoder": ENCODER,
           "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "head": {"type": "logistic", "C": C}, "n_development": len(ydev),
           "calibration": calibration, "selective": test_selective, "temperature": round(float(T), 3), "min_confidence_cal": round(mc, 3),
           "dataset_sha256": hashlib.sha256((a.dataset / "test.jsonl").read_bytes()).hexdigest(),
           "n_train": len(ytr), "n_calibration": len(yca), **metrics(yte, pte, labels, mc),
           "status": "SHADOW_ONLY", "authority": False,
           "note": "Source declarations validated; grouped partitions; identity not independently verified; observes, never decides."}
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    np.savez(a.out / "head.npz", coef=clf.coef_, intercept=clf.intercept_, labels=np.array(labels), T=T, min_confidence=mc,
             min_margin=calibration["min_margin"], abstain_all=calibration["abstain_all"])
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1", "ece", "temperature", "min_confidence_cal")}))


if __name__ == "__main__":
    main()
