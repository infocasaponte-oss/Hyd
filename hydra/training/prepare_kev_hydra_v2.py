# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Deduplicate reviewed development data into Kev's labelled-request contract."""
import json
from pathlib import Path

from hydra.training.verified_corpus import sha256

from hydra.router.decision_contract import CRITERIA


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Kev dataset version exists")
    source = Path("data/human-dev-v2.jsonl")
    unique = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("training_allowed") is not True:
            continue
        text, label = row["text"], row["expected"]
        key = " ".join(text.casefold().split())
        if label not in CRITERIA:
            raise ValueError("unsupported task label")
        if key in unique and unique[key][1] != label:
            raise ValueError("conflicting reviewed labels")
        unique.setdefault(key, (text, label))
    output.mkdir(parents=True)
    rows = [{"state": text, "questions": {"task": {"type": "choice", "criteria": CRITERIA,
             "label": label, "src": "hydra-reviewed-synthetic-dev-v2"}}} for text, label in unique.values()]
    train = output / "train.jsonl"
    train.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")
    manifest = {"kind": "reviewed_synthetic_development", "source_sha256": sha256(source),
                "train_sha256": sha256(train), "examples": len(rows), "labels": list(CRITERIA),
                "limitations": "200 unique template examples after deduplication; not human-authored blind evaluation",
                "frozen_tests_read": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/kev-hydra-v2")), indent=2))
