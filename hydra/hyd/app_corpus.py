# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hyd evaluator-app corpus: validate the exported JSONL, freeze splits, report per-class metrics.

    python -m hydra.hyd.app_corpus build  --corpus hyd-real-corpus-AAAA-MM-DD.jsonl --out data/hyd-app-corpus-v1
    python -m hydra.hyd.train --train data/hyd-app-corpus-v1/train.jsonl \
        --calibration data/hyd-app-corpus-v1/calibration.jsonl --out experiments/hyd-app-v1 --epochs 80
    python -m hydra.hyd.app_corpus report --dataset data/hyd-app-corpus-v1/test.jsonl \
        --model-dir experiments/hyd-app-v1 --out experiments/hyd-app-v1/test-per-class.json

Questions are copied verbatim (never rewritten). Only rows with consent=true, real=true and
suspect_template=false are admitted. Split is frozen by SHA-256 of the normalised text
(70 % train / 15 % calibration / 15 % test), so a question never changes partition as the corpus grows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from hydra.router.decision_contract import CRITERIA


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def split_of(text: str) -> str:
    h = int(hashlib.sha256(normalized(text).encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 70 else ("calibration" if h < 85 else "test")


def validate(path: Path) -> tuple[list[dict], dict]:
    rows, errors = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        m = r.get("meta", {})
        if not isinstance(r.get("text"), str) or not r["text"].strip():
            errors.append(f"line {n}: empty text")
        elif r.get("expected") not in CRITERIA:
            errors.append(f"line {n}: unknown label {r.get('expected')!r}")
        elif m.get("consent") is not True:
            errors.append(f"line {n}: no consent")
        elif m.get("real") is not True or m.get("suspect_template"):
            errors.append(f"line {n}: not real / suspect template")
        else:
            rows.append(r)
    labels, seen, dups = {}, set(), 0
    for r in rows:
        k = normalized(r["text"])
        labels.setdefault(k, set()).add(r["expected"])
        dups += (k, r["expected"]) in seen
        seen.add((k, r["expected"]))
    counts = Counter(r["expected"] for r in rows)
    report = {"valid_rows": len(rows), "errors": errors[:50], "n_errors": len(errors), "duplicates": dups,
              "conflicts": sum(len(v) > 1 for v in labels.values()),
              "missing_labels": [l for l in CRITERIA if l not in counts],
              "per_class": {l: counts.get(l, 0) for l in CRITERIA},
              "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return rows, report


def build(corpus: Path, out: Path) -> dict:
    rows, report = validate(corpus)
    if report["n_errors"] or report["duplicates"] or report["conflicts"] or report["missing_labels"]:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
    out.mkdir(parents=True, exist_ok=True)
    parts = {"train": [], "calibration": [], "test": []}
    for r in rows:
        s = split_of(r["text"])
        h = hashlib.sha256(r["text"].encode()).hexdigest()
        parts[s].append({"id": f"app-{h[:16]}", "split": s, "input": {"query": r["text"]},
                         "output": {"task_type": r["expected"]}, "source": "hyd-evaluator-app",
                         "training_allowed": s == "train", "consent": True,
                         "rights": {"license": "proprietary-hydra-authored", "verified": True},
                         "prompt_sha256": h})
    for s, v in parts.items():
        (out / f"{s}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in v), encoding="utf-8")
    report["splits"] = {s: {"n": len(v), "per_class": dict(Counter(x["output"]["task_type"] for x in v))}
                        for s, v in parts.items()}
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def report(dataset: Path, model_dir: Path) -> dict:
    from hydra.hyd.model import CandidateRanker
    model = CandidateRanker.load(model_dir / "model.json")
    cal = json.loads((model_dir / "calibration.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    labels = list(CRITERIA)
    cm = {a: Counter() for a in labels}
    confs, hits = [], []
    for r in rows:
        p = model.probabilities(r["input"]["query"], None, CRITERIA)
        sel = max(p, key=p.get)
        cm[r["output"]["task_type"]][sel] += 1
        confs.append(p[sel]); hits.append(sel == r["output"]["task_type"])
    per = {}
    for l in labels:
        tp = cm[l][l]; fp = sum(cm[o][l] for o in labels) - tp; fn = sum(cm[l].values()) - tp
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
        per[l] = {"precision": round(pr, 3), "recall": round(rc, 3),
                  "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0, "support": sum(cm[l].values())}
    ece, n = 0.0, len(rows)
    for i in range(10):
        idx = [j for j, c in enumerate(confs) if i / 10 < c <= (i + 1) / 10]
        if idx:
            ece += len(idx) / n * abs(sum(hits[j] for j in idx) / len(idx) - sum(confs[j] for j in idx) / len(idx))
    coverage = {}
    for th in (0.0, 0.4, 0.55, 0.7, 0.85, cal.get("min_confidence", 0.95)):
        acc = [h for h, c in zip(hits, confs) if c >= th]
        coverage[str(th)] = {"coverage": round(len(acc) / n, 3), "accuracy": round(sum(acc) / len(acc), 3) if acc else None}
    return {"format": "hyd-app-per-class/1", "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "model_revision": model.revision, "temperature": model.temperature, "n": n,
            "accuracy": round(sum(hits) / n, 3), "macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3),
            "ece": round(ece, 3), "per_class": per, "min_confidence": coverage,
            "confusion": {a: dict(cm[a]) for a in labels}, "status": "SHADOW_ONLY",
            "note": "Test partition frozen by hash; same evaluator pool as train, not independent promotion evidence."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--corpus", type=Path, required=True); b.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report"); r.add_argument("--dataset", type=Path, required=True)
    r.add_argument("--model-dir", type=Path, required=True); r.add_argument("--out", type=Path)
    a = ap.parse_args()
    res = build(a.corpus, a.out) if a.cmd == "build" else report(a.dataset, a.model_dir)
    if a.cmd == "report" and a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
