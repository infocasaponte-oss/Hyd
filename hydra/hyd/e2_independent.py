"""E2 · External independent evaluation (HYD-020, SHADOW_ONLY).

Measures E2 (e2-semantic-v1) and the current Hyd model on questions from
accounts that did NOT take part in training. Real app records only:
exact text, exact consent, no rewriting. Deduplicates exact copies,
excludes training accounts and template-mould questions (they are only
excluded from the evaluation, never deleted or edited).

Usage:
  python3 -m hydra.hyd.e2_independent \
    --external external-records.jsonl \
    --train-accounts train_accounts.txt \
    --head experiments/e2-semantic-v1/head.npz \
    --out experiments/e2-independent-v1
"""
from __future__ import annotations
import argparse, json, re, unicodedata
from collections import Counter
from pathlib import Path
import numpy as np

RISKY = ("abstain", "high_risk_review", "security", "privacy")


def norm(q: str) -> str:
    return " ".join(unicodedata.normalize("NFC", q).lower().split())


def load_external(path: Path, train_accounts: set[str]):
    """Returns per-account {who, questions, labels}; real text kept verbatim."""
    seen: set[tuple[str, str]] = set()
    people: dict[str, dict] = {}
    stats = {"rows": 0, "copies": 0, "in_training": 0, "mould_excluded": 0, "evaluated": 0}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        stats["rows"] += 1
        who = r["account"]
        key = (who, norm(r["question"]))
        if key in seen:
            stats["copies"] += 1
            continue
        seen.add(key)
        if who in train_accounts:
            stats["in_training"] += 1
            continue
        if r.get("suspect_template"):
            stats["mould_excluded"] += 1
            continue
        p = people.setdefault(who, {"questions": [], "labels": []})
        p["questions"].append(r["question"])  # byte-for-byte, no trim
        p["labels"].append(r["expected_label"])
        stats["evaluated"] += 1
    return people, stats


def metrics(y, sel, labels):
    hits = np.array([s == t for s, t in zip(sel, y)])
    cm = {a: Counter() for a in labels}
    for t, s in zip(y, sel):
        cm[t][s] += 1
    per = {}
    for l in labels:
        tp = cm[l][l]; fp = sum(cm[o][l] for o in labels) - tp; fn = sum(cm[l].values()) - tp
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
        per[l] = {"precision": round(pr, 3), "recall": round(rc, 3),
                  "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0}
    return {"n": len(y), "accuracy": round(float(hits.mean()), 3),
            "macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3), "per_class": per}


def abstain_metrics(y, pred):
    """P/R/F1 for the abstain class only (1 = abstain)."""
    yb = np.array([t == "abstain" for t in y]); pb = np.array([s == "abstain" for s in pred])
    tp = int((yb & pb).sum()); fp = int((~yb & pb).sum()); fn = int((yb & ~pb).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
    return {"abs_p": round(pr, 3), "abs_r": round(rc, 3),
            "abs_f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--external", type=Path, required=True)
    ap.add_argument("--train-accounts", type=Path, required=True)
    ap.add_argument("--head", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from sentence_transformers import SentenceTransformer

    train_accounts = {l.strip() for l in a.train_accounts.read_text().splitlines() if l.strip()}
    people, stats = load_external(a.external, train_accounts)
    head = np.load(a.head, allow_pickle=True)
    coef, intercept, labels, T = head["coef"], head["intercept"], list(head["labels"]), float(head["T"])

    enc = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
    rows = []
    for who, p in people.items():
        E = enc.encode(p["questions"], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        z = E @ coef.T + intercept
        z = z - z.max(1, keepdims=True); e = np.exp(z / T); pr = e / e.sum(1, keepdims=True)
        pred = [labels[i] for i in pr.argmax(1)]
        m = metrics(p["labels"], pred, labels)
        rows.append({"who": who, "n": len(p["labels"]), "abstain_n": p["labels"].count("abstain"),
                     "e2": {**m, **abstain_metrics(p["labels"], pred)}})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "external-metrics.json").write_text(json.dumps({"stats": stats, "rows": rows}, ensure_ascii=False, indent=2))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
