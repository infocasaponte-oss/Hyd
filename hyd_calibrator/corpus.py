# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hyd evaluator-app corpus: validate the exported JSONL, freeze splits, report per-class metrics.

    python -m hyd_calibrator build --corpus hyd-real-corpus-AAAA-MM-DD.jsonl --out data/hyd-app-corpus-v1
    python -m hyd_calibrator report --dataset data/hyd-app-corpus-v1/test.jsonl \
        --model-dir experiments/hyd-app-v1 --out experiments/hyd-app-v1/test-per-class.json

Questions are copied verbatim (never rewritten). Consent and declared source rights are required.
suspect_template is an informational flag, not a prohibition. Split is frozen by SHA-256 of the normalised text
(70 % train / 15 % calibration / 15 % test), so a question never changes partition as the corpus grows.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .contract import CRITERIA
from .atomic import write_text_atomic
from .admission import require_consent_and_rights
from .annotations import validate_annotations


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
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {n}: invalid JSON")
            continue
        if not isinstance(r, dict) or not isinstance(r.get("meta"), dict):
            errors.append(f"line {n}: expected object and meta object")
            continue
        m = r.get("meta", {})
        if not isinstance(r.get("text"), str) or not r["text"].strip():
            errors.append(f"line {n}: empty text")
        elif not isinstance(r.get("expected"), str) or r["expected"] not in CRITERIA:
            errors.append(f"line {n}: unknown label {r.get('expected')!r}")
        elif len(r["text"]) > 50000:
            errors.append(f"line {n}: text exceeds 50000 characters")
        elif m.get("consent") is not True:
            errors.append(f"line {n}: no consent")
        elif m.get("real") is not True or not isinstance(m.get("suspect_template"), bool):
            errors.append(f"line {n}: explicit real and variant flags required")
        elif (
            not isinstance(r.get("rights"), dict)
            or r["rights"].get("verified") is not True
            or not isinstance(r["rights"].get("license"), str)
            or not r["rights"]["license"].strip()
        ):
            errors.append(f"line {n}: verified source rights required")
        else:
            require_consent_and_rights({"consent": m["consent"], "rights": r["rights"]})
            if "annotations" in r:
                try:
                    validate_annotations(r["annotations"], r["text"])
                except ValueError as error:
                    errors.append(f"line {n}: {error}")
                    continue
            rows.append(r)
    labels, seen, dups = {}, set(), 0
    for r in rows:
        k = normalized(r["text"])
        labels.setdefault(k, set()).add(r["expected"])
        dups += (k, r["expected"]) in seen
        seen.add((k, r["expected"]))
    counts = Counter(r["expected"] for r in rows)
    report = {
        "valid_rows": len(rows),
        "errors": errors[:50],
        "n_errors": len(errors),
        "duplicates": dups,
        "conflicts": sum(len(v) > 1 for v in labels.values()),
        "missing_labels": [label for label in CRITERIA if label not in counts],
        "per_class": {label: counts.get(label, 0) for label in CRITERIA},
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return rows, report


def build(corpus: Path, out: Path, *, grouped: bool = False, development: bool = False) -> dict:
    if out.exists():
        raise ValueError("output directory already exists; choose a new snapshot")
    rows, report = validate(corpus)
    if report["n_errors"] or report["duplicates"] or report["conflicts"] or report["missing_labels"]:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
    if out.resolve() == corpus.parent.resolve():
        raise ValueError("choose a separate output directory")
    assignments = None
    if development and not grouped:
        raise ValueError("development partition requires grouped splitting")
    if grouped:
        from .grouping import grouped_partitions
        assignments = grouped_partitions(rows, development=development)
    out.mkdir(parents=True, exist_ok=False)
    parts = {"train": [], "calibration": [], "test": []}
    if development:
        parts["development"] = []
    for index, r in enumerate(rows):
        s = assignments[index][0] if assignments else split_of(r["text"])
        h = hashlib.sha256(r["text"].encode()).hexdigest()
        parts[s].append(
            {
                "id": f"app-{h[:16]}",
                "split": s,
                "input": {"query": r["text"]},
                "output": {"task_type": r["expected"]},
                "source": "hyd-evaluator-app",
                "training_allowed": s == "train",
                "consent": True,
                "rights": dict(r["rights"]),
                "meta": dict(r["meta"]),
                "provenance_status": "source-declared",
                "prompt_sha256": h,
            }
        )
        if "annotations" in r:
            parts[s][-1]["annotations"] = validate_annotations(r["annotations"], r["text"])
        if assignments:
            parts[s][-1]["group_id"] = assignments[index][1]
    for s, v in parts.items():
        write_text_atomic(out / f"{s}.jsonl", "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in v))
    report["splits"] = {
        s: {"n": len(v), "per_class": dict(Counter(x["output"]["task_type"] for x in v))} for s, v in parts.items()
    }
    report["partition_sha256"] = {s: hashlib.sha256((out / f"{s}.jsonl").read_bytes()).hexdigest() for s in parts}
    report["partition_policy"] = "declared-person-family-components/1" if grouped else "normalized-text-hash/1"
    report["independence_verified"] = False
    report["variant_flag_rows_kept"] = sum(r["meta"]["suspect_template"] for r in rows)
    report["variant_flags_are_exclusions"] = False
    report["variant_family_boundaries_checked"] = grouped
    report["development_partition"] = development
    if assignments:
        report["n_groups"] = len({group for _, group in assignments})
    write_text_atomic(out / "manifest.json", json.dumps(report, ensure_ascii=False, indent=2))
    return report


def report(dataset: Path, model_dir: Path) -> dict:
    from .model import CandidateRanker
    from .evaluation import load_calibration, load_rows, selective

    model = CandidateRanker.load(model_dir / "model.json")
    cal = load_calibration(model_dir / "calibration.json", model)
    rows = load_rows(dataset)
    labels = list(CRITERIA)
    cm = {a: Counter() for a in labels}
    confs, hits, margins = [], [], []
    for r in rows:
        p = model.probabilities(r["input"]["query"], None, CRITERIA)
        sel = max(p, key=p.get)
        cm[r["output"]["task_type"]][sel] += 1
        confs.append(p[sel])
        hits.append(sel == r["output"]["task_type"])
        ordered = sorted(p.values(), reverse=True)
        margins.append(ordered[0] - ordered[1])
    per = {}
    for label in labels:
        tp = cm[label][label]
        fp = sum(cm[o][label] for o in labels) - tp
        fn = sum(cm[label].values()) - tp
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        per[label] = {
            "precision": pr,
            "recall": rc,
            "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0,
            "support": sum(cm[label].values()),
        }
    ece, n = 0.0, len(rows)
    for i in range(10):
        idx = [j for j, c in enumerate(confs) if min(int(c * 10), 9) == i]
        if idx:
            ece += len(idx) / n * abs(sum(hits[j] for j in idx) / len(idx) - sum(confs[j] for j in idx) / len(idx))
    coverage = {}
    for th in (0.0, 0.4, 0.55, 0.7, 0.85, cal.get("min_confidence", 0.95)):
        coverage[str(th)] = selective(confs, margins, hits, th, cal["min_margin"])
    return {
        "format": "hyd-app-per-class/2",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "calibration_sha256": hashlib.sha256((model_dir / "calibration.json").read_bytes()).hexdigest(),
        "runtime_implementation_verified": False,
        "selective": selective(
            confs, margins, hits, cal["min_confidence"], cal["min_margin"], abstain_all=cal.get("abstain_all", False)
        ),
        "model_revision": model.revision,
        "temperature": model.temperature,
        "n": n,
        "accuracy": sum(hits) / n,
        "macro_f1": sum(v["f1"] for v in per.values()) / len(per),
        "ece": ece,
        "per_class": per,
        "min_confidence": coverage,
        "confusion": {a: dict(cm[a]) for a in labels},
        "status": "SHADOW_ONLY",
        "note": "Test partition frozen by hash; same evaluator pool as train, not independent promotion evidence.",
    }
