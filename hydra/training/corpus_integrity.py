# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Validate declared replay against pinned parent rows before allocating a training model."""
import json
from pathlib import Path

from hydra.training.verified_corpus import sha256


def validate_parent_replay(corpus: Path, manifest: dict) -> None:
    parent_hash = manifest.get("parent_manifest_sha256")
    if not parent_hash:
        return
    parents = [path for path in corpus.parent.glob("*/manifest.json")
               if path != corpus / "manifest.json" and sha256(path) == parent_hash]
    if len(parents) != 1:
        raise ValueError("cannot resolve the pinned parent corpus unambiguously")
    parent = parents[0].parent
    parent_manifest = json.loads(parents[0].read_text(encoding="utf-8"))
    for filename, entry in parent_manifest["files"].items():
        source = parent / filename
        if sha256(source) != entry["sha256"]:
            raise ValueError("parent corpus hash mismatch")
        inherited = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
        current = [json.loads(line) for line in (corpus / filename).read_text(encoding="utf-8").splitlines()]
        by_id = {row["id"]: row for row in current}
        if len(by_id) != len(current):
            raise ValueError("duplicate replay identifier")
        if any(by_id.get(row["id"]) != row for row in inherited):
            raise ValueError(f"inherited corpus rows changed: {filename}; check UTF-8 and partition integrity")
