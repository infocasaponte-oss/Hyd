# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded error mining with executable labels and replay; never mutates live weights.

This first adapter admits only reproduced HYDRA-authored generator records.
Runtime experiences remain subject to HYDRA's existing evidence/rights gates.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import uuid
from collections import Counter
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.corpus.artifact_privacy import _finding_types
from hydra.hyd.corpus import DOMAINS, SPLITS, make_record
from hydra.hyd.model import CandidateRanker, render
from hydra.hyd.stage1 import WorkLease
from hydra.hyd.train_typed import options, read_partition
from hydra.training.base_corpus import file_sha256


def verified_source(corpus: Path) -> tuple[dict, dict[str, list[dict]]]:
    """A claimed oracle/verified=True is insufficient: reproduce every record."""
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    generator = Path(__file__).with_name("corpus.py")
    if (manifest.get("format") != "hyd-typed-corpus/3"
            or manifest.get("generator_sha256") != file_sha256(generator)
            or manifest.get("domains") != list(DOMAINS)):
        raise ValueError("only the current executable authored corpus is admitted")
    partitions = {}
    for split in SPLITS:
        name = split + ".jsonl"
        metadata = manifest["files"][name]
        if file_sha256(corpus / name) != metadata["sha256"]:
            raise ValueError("source partition checksum mismatch")
        rows = read_partition(corpus / name, split)
        count = metadata["records"]
        if count != len(rows) or count % len(DOMAINS) or not 1 <= count // len(DOMAINS) <= 100000:
            raise ValueError("invalid generator record count")
        expected = [make_record(domain, split, index, manifest["seed"])
                    for domain in DOMAINS for index in range(count // len(DOMAINS))]
        if render(rows) != render(expected):
            raise ValueError("source labels/state do not reproduce the executable generator")
        partitions[split] = rows
    return manifest, partitions


def prepare(corpus: Path, model: Path, out: Path, *, max_error_copies: int = 300) -> dict:
    if not 0 <= max_error_copies <= 10000:
        raise ValueError("invalid error replay budget")
    if out.exists():
        raise FileExistsError("use a new immutable self-learning round")
    manifest, partitions = verified_source(corpus)
    metadata = json.loads(model.read_text(encoding="utf-8"))
    if metadata.get("format") == "hyd-contextual-ranker/1":
        from hydra.hyd.neural import ContextRanker
        ranker = ContextRanker.load(model)
    else:
        ranker = CandidateRanker.load(model)
    errors, counts, quarantined = [], Counter(), 0
    training = []
    privacy_findings = Counter()
    # Replay every original example; bounded extra errors cannot dominate the round.
    for row in partitions["train"]:
        findings = _finding_types(render({"state": row["state"], "question": row["question"]}))
        if findings:
            quarantined += 1
            privacy_findings.update(findings)
            continue
        training.append(row)
        question = row["question"]
        probability = ranker.probabilities(row["state"], question.get("instructions"), options(question))
        if (set(probability) != set(row["target"])
                or any(not math.isfinite(p) or p < 0 for p in probability.values())
                or abs(math.fsum(probability.values()) - 1) > 1e-6):
            raise ValueError("invalid scorer distribution")
        expected = max(row["target"], key=row["target"].get)
        selected = min(probability, key=lambda key: (-probability[key], key))
        counts[row["domain"] + ":scored"] += 1
        if selected != expected:
            errors.append(row)
            counts[row["domain"] + ":errors"] += 1
    if not training:
        raise ValueError("no privacy-admitted training examples remain")
    # Deterministic round-robin across error domains avoids first-domain bias.
    groups = {domain: [row for row in errors if row["domain"] == domain] for domain in DOMAINS}
    extras = []
    budget = min(max_error_copies, len(training) // 2, len(errors))
    offset = 0
    while len(extras) < budget:
        for domain in DOMAINS:
            if offset < len(groups[domain]) and len(extras) < budget:
                extras.append(groups[domain][offset])
        offset += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with WorkLease(out.parent / "self-learning.lock"):
        if out.exists():
            raise FileExistsError("self-learning round already exists")
        temporary = out.with_name(out.name + ".partial-" + uuid.uuid4().hex[:8])
        temporary.mkdir()
        files = {}
        for split in SPLITS:
            destination = temporary / (split + ".jsonl")
            if split == "train":
                text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in training + extras)
                write_text_atomic(destination, text)
            else:
                # Exact bytes preserve fixed evaluation partitions: no feedback leakage.
                destination.write_bytes((corpus / destination.name).read_bytes())
            files[destination.name] = {"sha256": file_sha256(destination),
                "records": len(training) + len(extras) if split == "train" else len(partitions[split])}
        report = {"format": "hyd-self-learning-round/1", "status": "PREPARED_NOT_TRAINED",
            "source_manifest_sha256": file_sha256(corpus / "manifest.json"),
            "source_generator_sha256": manifest["generator_sha256"],
            "mining_implementation_sha256": file_sha256(Path(__file__)),
            "model_sha256": file_sha256(model), "seed": manifest["seed"], "files": files,
            "training_examples": len(training), "observed_errors": len(errors), "extra_error_copies": len(extras),
            "domain_counts": dict(counts), "independent_test": False, "training_started": False,
            "privacy_quarantined_training_records": quarantined, "privacy_findings": dict(privacy_findings),
            "authority_enabled": False, "production_config_changed": False,
            "limitations": ["Errors mined only from training; evaluation partitions unchanged.",
                "Replay reweights verified errors, does not create new facts or certify improvement.",
                "No general runtime feedback admission, online weight updates or automatic promotion."]}
        write_text_atomic(temporary / "manifest.json", json.dumps(report, ensure_ascii=False, indent=2))
        os.replace(temporary, out)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-error-copies", type=int, default=300)
    args = parser.parse_args()
    print(json.dumps(prepare(args.corpus, args.model, args.out, max_error_copies=args.max_error_copies), indent=2))
