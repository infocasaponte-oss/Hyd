# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Admission of explicitly human-authored holdouts; never converts synthetic data to human."""
import json
from pathlib import Path

from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256


def freeze(source: Path, output: Path, training: list[Path], minimum=100):
    if output.exists():
        raise FileExistsError("frozen test cannot be overwritten")
    if minimum < 100:
        raise ValueError("certification needs at least 100 independently authored cases")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if len(rows) < minimum:
        raise ValueError("insufficient human cases; drafts do not certify")
    ids, prompts = set(), set()
    training_prompts = {normalized(r["messages"][1]["content"]) for path in training
                        for r in map(json.loads,path.read_text(encoding="utf-8").splitlines())}
    admitted = []
    for row in rows:
        if row.get("authorship") != "human" or row.get("review_status") != "approved" or not row.get("author") or not row.get("reviewer"):
            raise ValueError("human authorship and review attestation required; do not relabel synthetic examples")
        if row.get("training_allowed") is not False or row.get("kind") not in ("json","literal"):
            raise ValueError("verified expected format and explicit training exclusion required")
        if not all(isinstance(row.get(k),str) and row[k].strip() for k in ("id","prompt","expected")):
            raise ValueError("nonempty ID, prompt and expected answer required")
        key = normalized(row["prompt"])
        if row["id"] in ids or key in prompts or key in training_prompts:
            raise ValueError("duplicate or training-contaminated human case")
        if row["kind"] == "json":
            json.loads(row["expected"])
        ids.add(row["id"])
        prompts.add(key)
        admitted.append(dict(id=row["id"],family=row.get("family","human-instruction"),training_allowed=False,
            messages=[dict(role="system",content="Eres HYDRA. Sigue la instrucción del usuario."),
                      dict(role="user",content=row["prompt"]),dict(role="assistant",content=row["expected"])],
            verification=dict(kind=row["kind"],expected=row["expected"],passed=True),
            provenance=dict(authorship="human",author=row["author"],reviewer=row["reviewer"],source_sha256=sha256(source))))
    output.mkdir(parents=True)
    path = output/"test.jsonl"
    path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in admitted),encoding="utf-8")
    manifest = dict(format="hydra-human-holdout/1",authorship_attested=True,
                    source_sha256=sha256(source),training_hashes={str(p):sha256(p) for p in training},
                    files={"test.jsonl":dict(sha256=sha256(path),examples=len(admitted))},
                    approved=False,limitations="Human authorship is explicitly attested, not inferred by software; exact-match scope only.")
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest
