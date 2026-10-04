# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus integrity and release gates for staged HYDRA training."""
import hashlib
import json
import math
from pathlib import Path


def content_key(row):
    messages = row["messages"]
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("sample must end with assistant")
    if any(not isinstance(m.get("content"), str) or not m["content"].strip() for m in messages):
        raise ValueError("empty or invalid message")
    if any(any(marker in m["content"] for marker in ("\u00c3\u00b3", "\u00c3\u00a1", "\u00c3\u00a9", "\ufffd")) for m in messages):
        raise ValueError("suspected UTF-8 corruption; quarantine and review the source")
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_corpus(root: Path):
    if (root / "QUARANTINED.json").exists():
        raise ValueError("quarantined corpus")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    seen, identifiers, counts = {}, set(), {}
    for filename, entry in manifest["files"].items():
        path = root / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"hash mismatch: {filename}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            key = content_key(row)
            if key in seen:
                raise ValueError(f"duplicate example: {seen[key]} / {filename}")
            if row["id"] in identifiers:
                raise ValueError("duplicate identifier")
            identifiers.add(row["id"])
            seen[key] = filename
        counts[filename] = len(rows)
        if len(rows) != entry["examples"]:
            raise ValueError("manifest count mismatch")
    return {"counts": counts, "exact_overlap": 0,
            "semantic_independence_certified": False}


def release_gate(evidence):
    """Fail closed when an essential release claim has no evidence."""
    required = {"objective_accuracy": .90, "minimum_family_accuracy": .85,
                "semantic_human_acceptance": .90, "json_validity": .99,
                "json_content_accuracy": .95, "citation_support_precision": .95,
                "retrieval_relevance": .90, "router_macro_f1": .90,
                "router_coverage": .80, "router_selective_precision": .95}
    failures = [name for name, threshold in required.items()
                if not isinstance(evidence.get(name), (int, float))
                or isinstance(evidence.get(name), bool) or not math.isfinite(evidence[name])
                or evidence[name] < threshold]
    for name, limit in {"router_ece": .05, "quantization_drop_percentage_points": 2,
                        "runtime_error_rate": .01}.items():
        value = evidence.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
            failures.append(name)
    for name in ("independent_test", "human_review_complete", "artifact_bound",
                 "soak_passed", "rollback_tested", "corpus_review_complete"):
        if evidence.get(name) is not True:
            failures.append(name)
    return {"eligible": not failures, "approved": False, "failures": failures}
