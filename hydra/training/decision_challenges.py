# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Generate reproducible synthetic challenge proposals. Labels require human review."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from hydra.training.decision_active_learning import read_rows, text_label
from hydra.training.evidence_io import write_json


def generate(scenarios: Path, out: Path, seed=42, limit=40):
    if out.exists() or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("new output and limit 1..1000 required")
    rows = read_rows(scenarios)
    if not rows or any(r.get("split") in ("test", "reserved_test", "calibration", "dev", "cal_prob", "cal_policy")
                       or r.get("training_allowed") is not True for r in rows):
        raise ValueError("challenge generator cannot access held-out or unapproved scenarios")
    proposals, seen = [], set()
    prefixes = ("Me ayudas con esta petición: ", "Quero axuda con isto: ", "Consulta breve: ", "Por favor: ")
    rng = random.Random(seed)
    variants = [(row, prefix) for row in rows for prefix in prefixes]
    rng.shuffle(variants)
    for source, prefix in variants:
        original, label = text_label(source)
        text = prefix + original
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        group = source.get("group_id") or source.get("template_id") or source.get("family")
        if not group or group == label:
            raise ValueError("scenario identity required")
        proposals.append({"id": "challenge-" + digest, "text": text, "text_sha256": digest,
            "expected": None, "suggested_label": label, "source_kind": "synthetic",
            "group_id": group, "source": "controlled-prefix-proposal", "split": "pool",
            "training_allowed": False, "parent_id": source["id"],
            "rights": source.get("rights", {}), "consent": source.get("consent", False),
            "generator": {"seed": seed, "version": 1, "requires_human_label": True,
                          "transformation_not_certified_label_preserving": True}})
        if len(proposals) == limit:
            break
    out.mkdir(parents=True)
    path = out / "proposals.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in proposals), encoding="utf-8")
    manifest = {"format": "hyd-challenge-proposals/1", "requested": limit, "generated": len(proposals),
        "source_sha256": hashlib.sha256(scenarios.read_bytes()).hexdigest(), "seed": seed,
        "proposals_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "independent_test": False,
        "status": "PENDING_HUMAN_REVIEW", "source_kind": "synthetic"}
    write_json(out / "manifest.json", manifest)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenarios", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--limit", type=int, default=40)
    a = p.parse_args()
    print(json.dumps(generate(a.scenarios, a.out, a.seed, a.limit), indent=2))


if __name__ == "__main__":
    main()
