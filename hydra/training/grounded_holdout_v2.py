# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Sealed grounded holdout v2: private wordings, mandatory exclusions, complete or nothing.

grounded_holdout_v1 put its "unseen" wordings in the repository, so they became visible to every
later candidate; it stays valid only for candidates trained before it was published (v3-v5). v2:
- reads the wordings from a private JSON file kept outside git; only its sha256 is recorded;
- refuses to build without both corpus exclusions and BOE snapshot exclusions (otherwise the
  output cannot claim independence);
- refuses to seal a partial set: every family must reach its quota and the repeal balance its caps;
- pins the sha256 of every generation-critical helper, not only this file.
Report aggregate and per-family scores only; never train or tune on these cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.training.grounded_corpus_v1 import (
    PERMISSIVE, SYSTEM, boe_candidates, boe_url, contract, length_check, read_jsonl, source_sha256,
)
from hydra.training.grounded_corpus_v2 import code_candidates, verify
from hydra.training.grounded_holdout_v1 import QUOTAS, REPEALED_SHARE, used_document_ids
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256

HELPERS = ("training/grounded_corpus_v1.py", "training/grounded_corpus_v2.py", "training/grounded_holdout_v1.py",
           "training/instruction_corpus_v4.py", "training/verified_corpus.py", "corpus/gates.py")


def helper_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    return {name: source_sha256(package / name) for name in HELPERS}


def load_wordings(path: Path) -> tuple[dict[str, str], str]:
    wordings = json.loads(path.read_text(encoding="utf-8"))
    if set(wordings) != set(QUOTAS) or not all(isinstance(w, str) and w.strip() for w in wordings.values()):
        raise ValueError("private wordings must define one non-empty wording per family")
    return wordings, hashlib.sha256(path.read_bytes()).hexdigest()


def build(output: Path, boe: Path, code: Path, wordings_file: Path, exclude_corpora: list[Path],
          exclude_boe_snapshots: list[Path], exclude_holdouts: list[Path] | None = None,
          tokenizer: Path | None = None, max_tokens: int = 768) -> dict:
    if output.exists():
        raise FileExistsError("the holdout is sealed: build a new version instead of overwriting")
    if not exclude_corpora or not exclude_boe_snapshots:
        raise ValueError("an independent holdout needs both corpus and BOE snapshot exclusions")
    wordings, wordings_sha = load_wordings(wordings_file)
    used = used_document_ids(exclude_corpora)
    for snapshot in exclude_boe_snapshots:
        used.update(row["document_id"] for row in read_jsonl(snapshot)[0])
    for holdout in exclude_holdouts or []:
        used.update(json.loads(line)["provenance"]["document_id"]
                    for line in holdout.read_text(encoding="utf-8").splitlines() if line.strip())
    gate = PrivacyGate()
    fits, length_policy = length_check(tokenizer, max_tokens)
    counts = dict.fromkeys(QUOTAS, 0)
    caps = {"si": QUOTAS["boe_repealed"] - int(QUOTAS["boe_repealed"] * (1 - REPEALED_SHARE)),
            "no": int(QUOTAS["boe_repealed"] * (1 - REPEALED_SHARE))}
    repeal = {"si": 0, "no": 0}
    rows: list[dict] = []
    stats = {"excluded_used": 0, "privacy_rejected": 0, "verification_failed": 0, "too_long": 0}

    def admit(document_id: str, candidates, provenance: dict) -> None:
        for family, fields, source, answer in sorted(candidates, key=lambda c: counts[c[0]] / QUOTAS[c[0]]):
            if counts[family] >= QUOTAS[family]:
                continue
            polarity = ("si" if answer.startswith("Sí") else "no") if family == "boe_repealed" else None
            if polarity and repeal[polarity] >= caps[polarity]:
                continue
            _, credential, pii = gate.scan_text(source + "\n" + answer)
            if credential or pii:
                stats["privacy_rejected"] += 1
                continue
            if not verify(family, fields, source, answer):
                stats["verification_failed"] += 1
                continue
            messages = [{"role": "system", "content": SYSTEM + source},
                        {"role": "user", "content": contract(wordings[family].format(**fields))},
                        {"role": "assistant", "content": answer}]
            if not fits(messages):
                stats["too_long"] += 1
                continue
            rows.append({"id": f"grounded-holdout-v2-{family}-{counts[family]}", "family": family,
                         "wording_family": f"{family}-private", "split": "holdout", "training_allowed": False,
                         "messages": messages, "provenance": provenance,
                         "verification": {"kind": "deterministic_extractive", "passed": True,
                                          "source_sha256": hashlib.sha256(source.encode()).hexdigest()}})
            counts[family] += 1
            if polarity:
                repeal[polarity] += 1
            return

    boe_rows, boe_sha = read_jsonl(boe)
    for record in sorted(boe_rows, key=lambda r: hashlib.sha256(("v2" + r["document_id"]).encode()).hexdigest()):
        if record["document_id"] in used:
            stats["excluded_used"] += 1
            continue
        admit(record["document_id"], boe_candidates(record), {
            "source": "BOE datos abiertos, legislación consolidada", "document_id": record["document_id"],
            "url": boe_url(record["document_id"]), "license": "Reutilización de datos del BOE con cita de la fuente"})
    code_rows, code_sha = read_jsonl(code)
    records = [r for r in code_rows if set(r.get("detected_licenses") or []) and set(r["detected_licenses"]) <= PERMISSIVE]
    for i, record in enumerate(sorted(records, key=lambda r: hashlib.sha256(("v2" + r["id"]).encode()).hexdigest())):
        if record["id"] in used:
            stats["excluded_used"] += 1
            continue
        candidates, _ = code_candidates(record, f"resolver_{['tramo', 'cuota', 'saldo'][i % 3]}_{i % 83}")
        admit(record["id"], candidates, {"source": "common-pile/stackv2_edu_filtered", "document_id": record["id"],
                                         "repository": record["repo_name"], "path": record["path"],
                                         "license": record["detected_licenses"]})
    if counts != QUOTAS or repeal != caps:  # never seal a partial holdout
        raise ValueError(f"holdout underfilled: {counts} repeal {repeal} (targets {QUOTAS}, {caps})")
    keys = [normalized(r["messages"][0]["content"] + r["messages"][1]["content"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate holdout prompt")
    output.mkdir(parents=True)
    path = output / "holdout.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = {"version": "grounded-holdout-v2", "sealed": True, "independent_test": True, "approved": False,
                "generator_sha256": source_sha256(Path(__file__)), "helpers_sha256": helper_hashes(),
                "wordings_sha256": wordings_sha, "wordings": "private, kept outside git",
                "families": counts, "repeal_balance": repeal,
                "inputs": {"boe": {"path": str(boe), "sha256": boe_sha}, "code": {"path": str(code), "sha256": code_sha}},
                "excluded_corpora": [str(c) for c in exclude_corpora],
                "excluded_boe_snapshots": [str(s) for s in exclude_boe_snapshots],
                "excluded_holdouts": [str(h) for h in exclude_holdouts or []],
                "length_policy": length_policy, "rejections": stats,
                "files": {"holdout.jsonl": {"examples": len(rows), "sha256": sha256(path)}},
                "policy": "report aggregate and per-family scores only; never train or tune on these cases",
                "limitations": "code files may appear in HYDRA Base v0 pretraining data; BOE norms do not"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/hydra-grounded-holdout-v2"))
    parser.add_argument("--boe", type=Path, required=True)
    parser.add_argument("--code", type=Path, default=Path("data/sources/code/stackv2_edu_python_sample.jsonl"))
    parser.add_argument("--wordings", type=Path, required=True, help="private JSON kept outside git")
    parser.add_argument("--exclude-corpus", type=Path, action="append", required=True)
    parser.add_argument("--exclude-boe-snapshot", type=Path, action="append", required=True)
    parser.add_argument("--exclude-holdout", type=Path, action="append", default=[])
    parser.add_argument("--tokenizer", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.boe, args.code, args.wordings, args.exclude_corpus,
                           args.exclude_boe_snapshot, args.exclude_holdout, args.tokenizer), indent=2, ensure_ascii=False))
