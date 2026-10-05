"""E3 · Evaluation by abstain kind from human annotations (HYD-022).

Uses ONLY the «perigosa» / «falta de contexto» marks that each external
evaluator sets on their OWN abstain questions in the evaluator app
(hyd_abstain_annotations). One mark per record, owner-scoped. Template-
mould questions are excluded from the measurement.

For each person and each kind, reports E3 / E2 (share in 0–1):
  precision    — of the questions predicted abstain, how many are of that kind
  recall       — of the abstains of that kind, how many are predicted abstain
  false alarms — non-abstain questions of that person predicted abstain
Kinds with fewer than min_n marks are reported but flagged measured=false.

Usage:
  python3 -m hydra.hyd.e3_annotated \
    --external external-records.jsonl --annotations annotations.jsonl \
    --train-accounts train_accounts.txt \
    --e3-head experiments/e3-risk-v1/head.npz --e2-head experiments/e2-semantic-v1/head.npz \
    --out experiments/e3-annotated-v1 [--min-n 10]

annotations.jsonl rows: {"record_id", "kind": "dangerous"|"missing_context"}
external-records.jsonl rows: {"record_id", "account", "question", "expected_label", "suspect_template"}
"""
from __future__ import annotations
import argparse, json, unicodedata
from pathlib import Path
import numpy as np



def norm(q: str) -> str:
    return " ".join(unicodedata.normalize("NFC", q).lower().split())


def load(external: Path, annotations: Path, train_accounts: set[str]):
    ann = {}
    for line in annotations.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ann[r["record_id"]] = r["kind"]
    seen: set[str] = set()
    people: dict[str, dict] = {}
    for line in external.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        who, rid = r["account"], r["record_id"]
        if who in train_accounts or r.get("suspect_template") or rid in seen:
            continue
        seen.add(rid)
        p = people.setdefault(who, {"questions": [], "labels": [], "kinds": {}})
        p["questions"].append(r["question"])  # verbatim
        p["labels"].append(r["expected_label"])
        if rid in ann and r["expected_label"] == "abstain":
            p["kinds"][len(p["questions"]) - 1] = ann[rid]
    return people


def prf(kind_idx, abstain_pred, labels):
    """Precision/recall of predicting abstain on abstains of `kind`, plus
    false alarms over the person's non-abstain questions."""
    sel = set(np.flatnonzero(abstain_pred))
    tp = len(kind_idx & sel); fp = len(sel - kind_idx); fn = len(kind_idx - sel)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec is not None and rec is not None and prec + rec else None
    other = [i for i, t in enumerate(labels) if t != "abstain"]
    fa = float(np.mean([i in sel for i in other])) if other else None
    return prec, rec, fa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--external", type=Path, required=True)
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--train-accounts", type=Path, required=True)
    ap.add_argument("--e3-head", type=Path, required=True)
    ap.add_argument("--e2-head", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-n", type=int, default=10)
    a = ap.parse_args()
    from sentence_transformers import SentenceTransformer

    train_accounts = {l.strip() for l in a.train_accounts.read_text().splitlines() if l.strip()}
    people = load(a.external, a.annotations, train_accounts)
    h3 = np.load(a.e3_head, allow_pickle=True); h2 = np.load(a.e2_head, allow_pickle=True)
    l3 = [str(l) for l in h3["labels"]]; l2 = [str(l) for l in h2["labels"]]
    enc = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
    rows, total_marks = [], 0
    for who, p in people.items():
        E = enc.encode(p["questions"], batch_size=64, normalize_embeddings=True, show_progress_bar=False)

        def head_probs(Ei, head, labels):
            z = Ei @ head["coef"].T + head["intercept"]
            z = z - z.max(1, keepdims=True); e = np.exp(z / float(head["T"]))
            pr = e / e.sum(1, keepdims=True)
            return np.array([labels[i] for i in pr.argmax(1)]) if labels else pr.argmax(1)

        s3 = head_probs(E, h3, l3); s2 = head_probs(E, h2, l2)
        by_kind: dict[str, list[int]] = {}
        for i, k in p["kinds"].items():
            by_kind.setdefault(k, []).append(int(i))
        total_marks += sum(len(v) for v in by_kind.values())
        for kind, idx in sorted(by_kind.items()):
            idx_set = set(idx)
            for model, sel, l in (("e3", s3, l3), ("e2", s2, l2)):
                ap_, rc_, fa = prf(idx_set, sel == "abstain", p["labels"])
                rows.append({"who": who, "kind": kind, "n": len(idx), "model": model,
                             "precision": ap_, "recall": rc_, "false_alarm": fa,
                             "measured": len(idx) >= a.min_n and ap_ is not None and rc_ is not None})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "annotated-metrics.json").write_text(
        json.dumps({"annotations": total_marks, "min_n": a.min_n, "rows": rows}, ensure_ascii=False, indent=2))
    print(json.dumps({"annotations": total_marks, "rows": len(rows)}))


if __name__ == "__main__":
    main()
